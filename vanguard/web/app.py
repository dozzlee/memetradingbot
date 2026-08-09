import asyncio
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from vanguard import backtest, db, discovery
from vanguard.config import settings
from vanguard.core.wallet_tracker import watch_wallets
from vanguard.pipeline import on_buy
from vanguard.state import state

app = FastAPI(title="Vanguard Protocol")

STATIC_DIR = Path(__file__).parent / "static"


@app.on_event("startup")
async def startup():
    state.load()
    # Seed from .env on first run only — DB is authoritative after that,
    # so wallets added/removed via the dashboard survive a restart.
    for addr in settings.TRACKED_WALLETS:
        state.add_wallet(addr)


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


# --- trade ledger (manual — the bot never executes trades itself) ---

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
