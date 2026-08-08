"""Shared runtime state between the monitor loop and the web dashboard,
backed by SQLite (vanguard/db.py) so it survives restarts."""
import time
from dataclasses import dataclass, field

from vanguard import db


@dataclass
class AppState:
    running: bool = False
    started_at: float | None = None
    tracked_wallets: list[str] = field(default_factory=list)
    monitor_task: object = None  # asyncio.Task, set by the control API

    def load(self):
        db.init_db()
        self.tracked_wallets = db.list_wallets()

    def add_wallet(self, address: str):
        if address and address not in self.tracked_wallets:
            self.tracked_wallets.append(address)
            db.add_wallet(address)

    def remove_wallet(self, address: str):
        if address in self.tracked_wallets:
            self.tracked_wallets.remove(address)
            db.remove_wallet(address)

    def log_event(self, kind: str, wallet: str, mint: str, detail: str = ""):
        db.log_event(kind, wallet, mint, detail)

    def events(self, limit: int = 200):
        return db.list_events(limit)

    def log_alert(self, mint: str, risk_score, buy_sell_ratio: str, wallet: str):
        db.log_alert(mint, wallet, risk_score, buy_sell_ratio)

    def alerts(self, limit: int = 100):
        return db.list_alerts(limit)


state = AppState()
