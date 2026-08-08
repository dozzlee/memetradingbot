import asyncio
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from vanguard.config import settings
from vanguard.core.wallet_tracker import watch_wallets
from vanguard.pipeline import on_buy
from vanguard.state import state

app = FastAPI(title="Vanguard Protocol")

STATIC_DIR = Path(__file__).parent / "static"


@app.on_event("startup")
async def startup():
    state.tracked_wallets = list(settings.TRACKED_WALLETS)


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
        },
    }


@app.get("/api/events")
async def events():
    return state.events


@app.get("/api/alerts")
async def alerts():
    return state.alerts


class WalletPayload(BaseModel):
    address: str


@app.post("/api/wallets")
async def add_wallet(payload: WalletPayload):
    addr = payload.address.strip()
    if addr and addr not in state.tracked_wallets:
        state.tracked_wallets.append(addr)
    return {"tracked_wallets": state.tracked_wallets}


@app.delete("/api/wallets/{address}")
async def remove_wallet(address: str):
    if address in state.tracked_wallets:
        state.tracked_wallets.remove(address)
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
