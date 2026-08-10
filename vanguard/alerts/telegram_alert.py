"""Telegram side of the buy/sell flow: sends the cleared-token alert with
inline Buy/Skip buttons, and the plain notifications for fills/exits/errors.
Receiving the button taps themselves is handled by vanguard/alerts/telegram_bot.py
(this module only ever calls Telegram's outbound sendMessage/editMessageText/
answerCallbackQuery — no incoming state lives here)."""
import requests

from vanguard.config import settings

API_BASE = "https://api.telegram.org/bot{token}/{method}"


def _call(method: str, **params) -> dict:
    resp = requests.post(
        API_BASE.format(token=settings.TELEGRAM_BOT_TOKEN, method=method),
        json=params,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def send_text(text: str, reply_markup: dict | None = None) -> dict:
    payload = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return _call("sendMessage", **payload)


def send_buy_confirmation(mint: str, risk_score, buy_sell_ratio, solscan_url: str) -> dict:
    text = (
        f"*Token cleared*: `{mint}`\n"
        f"Risk score: {risk_score}\n"
        f"Buy/sell velocity: {buy_sell_ratio}\n"
        f"Position size: ${settings.POSITION_SIZE_USD:g}\n"
        f"[Solscan]({solscan_url})"
    )
    reply_markup = {
        "inline_keyboard": [[
            {"text": f"Buy ${settings.POSITION_SIZE_USD:g}", "callback_data": f"buy:{mint}"},
            {"text": "Skip", "callback_data": f"skip:{mint}"},
        ]]
    }
    return send_text(text, reply_markup)


def edit_message_text(message_id: int, text: str, reply_markup: dict | None = None) -> dict:
    payload = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return _call("editMessageText", **payload)


def clear_buttons(message_id: int, text: str) -> dict:
    """Edits a message's text and removes its inline keyboard in one call —
    used once a Buy/Skip button has been acted on, so it can't be tapped twice."""
    return edit_message_text(message_id, text, reply_markup={"inline_keyboard": []})


def answer_callback_query(callback_query_id: str, text: str = "", show_alert: bool = False) -> dict:
    return _call(
        "answerCallbackQuery",
        callback_query_id=callback_query_id,
        text=text,
        show_alert=show_alert,
    )
