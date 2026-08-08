"""In-memory shared state between the monitor loop and the web dashboard.
Single process, single asyncio event loop — no IPC/DB needed for now."""
import time
from dataclasses import dataclass, field


@dataclass
class AppState:
    running: bool = False
    started_at: float | None = None
    tracked_wallets: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)  # cleared / rejected / aborted / error
    alerts: list[dict] = field(default_factory=list)  # tokens that passed both gates
    monitor_task: object = None  # asyncio.Task, set by the control API

    def log_event(self, kind: str, wallet: str, mint: str, detail: str = ""):
        self.events.insert(0, {
            "ts": time.time(),
            "kind": kind,  # "buy_detected" | "rejected" | "abort" | "cleared" | "error"
            "wallet": wallet,
            "mint": mint,
            "detail": detail,
        })
        self.events = self.events[:200]

    def log_alert(self, mint: str, risk_score, buy_sell_ratio: str, wallet: str):
        self.alerts.insert(0, {
            "ts": time.time(),
            "mint": mint,
            "risk_score": risk_score,
            "buy_sell_ratio": buy_sell_ratio,
            "wallet": wallet,
        })
        self.alerts = self.alerts[:100]


state = AppState()
