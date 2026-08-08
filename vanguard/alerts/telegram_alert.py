"""Push filtered alerts to a private Telegram channel (PRD §2, Component A)."""
import requests

from vanguard.config import settings

SEND_URL = "https://api.telegram.org/bot{token}/sendMessage"


def send_alert(mint: str, risk_score, buy_sell_ratio, solscan_url: str) -> None:
    text = (
        f"*Token cleared*: `{mint}`\n"
        f"Risk score: {risk_score}\n"
        f"Buy/sell velocity: {buy_sell_ratio}\n"
        f"[Solscan]({solscan_url})"
    )
    resp = requests.post(
        SEND_URL.format(token=settings.TELEGRAM_BOT_TOKEN),
        json={
            "chat_id": settings.TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        },
        timeout=10,
    )
    resp.raise_for_status()
