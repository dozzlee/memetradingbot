import asyncio
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from vanguard import backtest, db, discovery
from vanguard.alerts import telegram_bot
from vanguard.config import settings
from vanguard.core.wallet_tracker import watch_wallets
from vanguard.execution import position_monitor
from vanguard.pipeline import on_buy
from vanguard.state import state
from vanguard.wallet import keystore, pricing

app = FastAPI(title="Vanguard Protocol")

STATIC_DIR = Path(__file__).parent / "static"


@app.on_event("startup")
async def startup():
    state.load()
    # Seed from .env on first run only — DB is authoritative after that,
    # so wallets added/removed via the dashboard survive a restart.
    for addr in settings.TRACKED_WALLETS:
        state.add_wallet(addr)

    # Listens for Buy/Skip taps regardless of whether wallet tracking is
    # running, so it always starts (not gated behind /api/control/start).
    if settings.TELEGRAM_BOT_TOKEN:
        state.telegram_bot_task = asyncio.create_task(telegram_bot.poll_updates())

    # Resume auto-sell monitoring for any position left open across a
    # restart (e.g. systemd Restart=on-failure) — otherwise a real position
    # would sit unmonitored with no take-profit/stop-loss watching it.
    for row in db.open_trades():
        monitor_task = asyncio.create_task(
            position_monitor.watch_position(
                row["id"], row["mint"], row["entry_price_usd"], row["token_amount"], row["decimals"]
            )
        )
        state.set_open_position(
            row["id"], row["mint"], row["entry_price_usd"], row["token_amount"], row["decimals"], monitor_task
        )


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
async def status():
    return {
        "running": state.running,
        "started_at": state.started_at,
        "uptime_seconds": (time.time() - state.started_at) if state.started_at else 0,
        "tracked_wallets": state.tracked_wallets,
        "config": {
            "safety_window_seconds": settings.SAFETY_WINDOW_SECONDS,
            "momentum_timeout_seconds": settings.MOMENTUM_TIMEOUT_SECONDS,
            "top10_concentration_limit": settings.TOP10_CONCENTRATION_LIMIT,
            "wallet_poll_interval_seconds": settings.WALLET_POLL_INTERVAL_SECONDS,
            "require_pumpfun_graduation": settings.REQUIRE_PUMPFUN_GRADUATION,
            "solana_tracker_enabled": bool(settings.SOLANA_TRACKER_API_KEY),
        },
    }


@app.get("/api/events")
async def events():
    return state.events()


@app.get("/api/alerts")
async def alerts():
    return state.alerts()


class WalletPayload(BaseModel):
    address: str


@app.post("/api/wallets")
async def add_wallet(payload: WalletPayload):
    state.add_wallet(payload.address.strip())
    return {"tracked_wallets": state.tracked_wallets}


@app.delete("/api/wallets/{address}")
async def remove_wallet(address: str):
    state.remove_wallet(address)
    return {"tracked_wallets": state.tracked_wallets}


@app.post("/api/control/start")
async def start_monitor():
    if state.running:
        return {"running": True}
    state.running = True
    state.started_at = time.time()
    state.monitor_task = asyncio.create_task(
        watch_wallets(on_buy, poll_interval=settings.WALLET_POLL_INTERVAL_SECONDS)
    )
    return {"running": True}


@app.post("/api/control/stop")
async def stop_monitor():
    if state.monitor_task:
        state.monitor_task.cancel()
        state.monitor_task = None
    state.running = False
    state.started_at = None
    return {"running": False}


# --- analysis (no funded wallet or live trigger required) ---

class InspectPayload(BaseModel):
    mint: str


@app.post("/api/inspect")
async def inspect(payload: InspectPayload):
    return await asyncio.to_thread(backtest.inspect_token, payload.mint.strip())


@app.get("/api/wallets/{address}/backtest")
async def wallet_backtest(address: str, max_buys: int = 20):
    return await asyncio.to_thread(backtest.backtest_wallet, address, max_buys)


@app.get("/api/discover")
async def discover(min_mcap: float = 500_000, max_tokens: int = 15):
    return await asyncio.to_thread(discovery.discover_wallets, min_mcap, max_tokens)


# --- execution wallet (custodial — see vanguard/wallet/keystore.py) ---

@app.get("/api/wallet")
async def get_wallet():
    address = keystore.get_address()
    if not address:
        return {"exists": False}

    sol_balance = await asyncio.to_thread(keystore.get_sol_balance, address)
    try:
        sol_price = await asyncio.to_thread(pricing.get_sol_price_usd)
        usd_balance = sol_balance * sol_price
    except Exception:
        sol_price = None
        usd_balance = None

    open_position = None
    if state.open_position:
        open_position = {k: v for k, v in state.open_position.items() if k != "monitor_task"}

    return {
        "exists": True,
        "address": address,
        "sol_balance": sol_balance,
        "sol_price_usd": sol_price,
        "usd_balance": usd_balance,
        "open_position": open_position,
        "config": {
            "position_size_usd": settings.POSITION_SIZE_USD,
            "max_capital_deployed_usd": settings.MAX_CAPITAL_DEPLOYED_USD,
            "take_profit_pct": settings.TAKE_PROFIT_PCT,
            "stop_loss_pct": settings.STOP_LOSS_PCT,
        },
    }


@app.post("/api/wallet/init")
async def init_wallet():
    try:
        address = await asyncio.to_thread(keystore.create_wallet)
    except keystore.WalletError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"address": address}


# --- trade ledger (manual entries from before/outside auto-trading;
# auto trades write here too, via db.open_trade(..., auto=True)) ---

class OpenTradePayload(BaseModel):
    mint: str
    wallet: str = ""
    entry_price_usd: float
    size_usd: float = 5.0
    notes: str = ""


class CloseTradePayload(BaseModel):
    exit_price_usd: float
    fees_usd: float = 0.0


@app.get("/api/trades")
async def list_trades():
    return db.list_trades()


@app.post("/api/trades")
async def open_trade(payload: OpenTradePayload):
    trade_id = db.open_trade(
        payload.mint, payload.wallet, payload.entry_price_usd, payload.size_usd, payload.notes
    )
    return {"id": trade_id}


@app.post("/api/trades/{trade_id}/close")
async def close_trade(trade_id: int, payload: CloseTradePayload):
    try:
        pnl = db.close_trade(trade_id, payload.exit_price_usd, payload.fees_usd)
    except ValueError:
        raise HTTPException(status_code=404, detail="trade not found")
    return {"pnl_usd": pnl}
