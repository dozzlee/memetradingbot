"""Receives Telegram button taps (the Buy/Skip confirmation on a cleared-token
alert — see telegram_alert.send_buy_confirmation) via long-polling getUpdates.
No public webhook needed, which matters since the dashboard/VPS is bound to
127.0.0.1 with no inbound port exposed (see deploy/vanguard.service)."""
import asyncio
import logging

import requests

from vanguard import db
from vanguard.alerts import telegram_alert
from vanguard.config import settings
from vanguard.execution import position_monitor, trader
from vanguard.state import state

logger = logging.getLogger("vanguard")

GET_UPDATES_URL = "https://api.telegram.org/bot{token}/getUpdates"


def _get_updates(offset: int | None) -> list[dict]:
    params = {"timeout": 25, "allowed_updates": '["callback_query"]'}
    if offset is not None:
        params["offset"] = offset
    resp = requests.get(
        GET_UPDATES_URL.format(token=settings.TELEGRAM_BOT_TOKEN), params=params, timeout=30
    )
    resp.raise_for_status()
    return resp.json().get("result", [])


async def _handle_buy(mint: str, callback_query_id: str, message_id: int, original_text: str):
    if state.open_position is not None:
        telegram_alert.answer_callback_query(
            callback_query_id,
            f"Already in a position ({state.open_position['mint'][:6]}...) — "
            f"max ${settings.MAX_CAPITAL_DEPLOYED_USD:g} deployed at once.",
            show_alert=True,
        )
        return

    telegram_alert.answer_callback_query(callback_query_id, "Buying...")
    try:
        result = await trader.execute_buy(mint)
    except Exception as e:
        logger.exception("buy failed for %s", mint)
        telegram_alert.clear_buttons(message_id, f"{original_text}\n\n❌ *Buy failed*: {e}")
        return

    trade_id = db.open_trade(
        mint=mint,
        wallet="",
        entry_price_usd=result["entry_price_usd"],
        size_usd=result["size_usd"],
        token_amount=result["token_amount"],
        decimals=result["decimals"],
        entry_tx_sig=result["tx_sig"],
        auto=True,
    )
    monitor_task = asyncio.create_task(
        position_monitor.watch_position(
            trade_id, mint, result["entry_price_usd"], result["token_amount"], result["decimals"]
        )
    )
    state.set_open_position(
        trade_id, mint, result["entry_price_usd"], result["token_amount"], result["decimals"], monitor_task
    )
    telegram_alert.clear_buttons(
        message_id,
        f"{original_text}\n\n✅ *Bought* — entry ${result['entry_price_usd']:.6f}, "
        f"exits automatically at +{settings.TAKE_PROFIT_PCT:g}%/-{settings.STOP_LOSS_PCT:g}%\n"
        f"[Tx](https://solscan.io/tx/{result['tx_sig']})",
    )


async def _handle_skip(mint: str, callback_query_id: str, message_id: int, original_text: str):
    telegram_alert.answer_callback_query(callback_query_id, "Skipped")
    telegram_alert.clear_buttons(message_id, f"{original_text}\n\n_Skipped._")


async def _handle_callback_query(cq: dict):
    data = cq.get("data", "")
    callback_query_id = cq["id"]
    message = cq.get("message") or {}
    message_id = message.get("message_id")
    original_text = message.get("text", "")

    action, _, mint = data.partition(":")
    if not mint or message_id is None:
        telegram_alert.answer_callback_query(callback_query_id, "Stale button")
        return

    if action == "buy":
        await _handle_buy(mint, callback_query_id, message_id, original_text)
    elif action == "skip":
        await _handle_skip(mint, callback_query_id, message_id, original_text)
    else:
        telegram_alert.answer_callback_query(callback_query_id)


async def poll_updates():
    """Runs for the lifetime of the app (started unconditionally at startup,
    not tied to the wallet monitor's start/stop) so Buy/Skip taps are always
    handled even while wallet tracking itself is stopped."""
    offset = None
    while True:
        try:
            updates = await asyncio.to_thread(_get_updates, offset)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("telegram getUpdates failed, retrying in 5s")
            await asyncio.sleep(5)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            cq = update.get("callback_query")
            if cq:
                try:
                    await _handle_callback_query(cq)
                except Exception:
                    logger.exception("failed handling callback_query %s", cq.get("id"))
