"""Watches one open auto-trade position and exits it automatically at the
fixed take-profit/stop-loss points (settings.TAKE_PROFIT_PCT / STOP_LOSS_PCT)
— no confirmation needed to exit, only to enter (see telegram_bot.py)."""
import asyncio
import logging

from vanguard import db
from vanguard.alerts import telegram_alert
from vanguard.config import settings
from vanguard.execution import trader
from vanguard.gates.momentum_gate import get_market_data
from vanguard.state import state

logger = logging.getLogger("vanguard")


async def watch_position(trade_id: int, mint: str, entry_price_usd: float, token_amount: float, decimals: int):
    try:
        while True:
            await asyncio.sleep(settings.POSITION_POLL_INTERVAL_SECONDS)

            try:
                data = await asyncio.to_thread(get_market_data, mint)
            except Exception:
                logger.exception("price poll failed for open position %s (%s)", trade_id, mint)
                continue
            if not data:
                continue
            price = float(data.get("priceUsd") or 0)
            if not price:
                continue

            change_pct = (price - entry_price_usd) / entry_price_usd * 100
            if change_pct >= settings.TAKE_PROFIT_PCT:
                reason = f"take-profit (+{change_pct:.0f}%)"
            elif change_pct <= -settings.STOP_LOSS_PCT:
                reason = f"stop-loss ({change_pct:.0f}%)"
            else:
                continue

            try:
                result = await trader.execute_sell(mint, token_amount, decimals)
            except Exception as e:
                logger.exception("auto-sell failed for trade %s (%s)", trade_id, mint)
                telegram_alert.send_text(
                    f"⚠️ Auto-sell FAILED for `{mint}` ({reason}): {e}\n"
                    f"Position is still open — will keep retrying, or close it manually."
                )
                continue  # keep watching; next poll retries the sell

            pnl = db.close_trade(
                trade_id,
                exit_price_usd=result["exit_price_usd"],
                fees_usd=0.0,
                exit_tx_sig=result["tx_sig"],
            )
            state.clear_open_position()
            telegram_alert.send_text(
                f"{'🟢' if pnl >= 0 else '🔴'} *Closed* `{mint}` — {reason}\n"
                f"PnL: ${pnl:+.2f}\n"
                f"[Tx](https://solscan.io/tx/{result['tx_sig']})"
            )
            return
    except asyncio.CancelledError:
        raise
