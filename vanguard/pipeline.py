"""The Stage 1 -> 2 -> 3 momentum-gate pipeline (PRD §4), wired to shared
state so the web dashboard can see every decision, not just alerts."""
import asyncio
import logging
import time

from vanguard.config import settings
from vanguard.core.holdings import insider_still_holding
from vanguard.gates.rug_gate import check_token
from vanguard.gates.momentum_gate import check_momentum, get_market_data
from vanguard.alerts.telegram_alert import send_alert
from vanguard.state import state

logger = logging.getLogger("vanguard")


async def on_buy(wallet: str, mint: str):
    logger.info("tracked wallet %s bought %s — running rug-gate", wallet, mint)
    state.log_event("buy_detected", wallet, mint)

    # Stage 1 — safety window
    await asyncio.sleep(settings.SAFETY_WINDOW_SECONDS)
    try:
        gate_result = await asyncio.to_thread(check_token, mint, settings.TOP10_CONCENTRATION_LIMIT)
    except Exception as e:
        logger.exception("rug-gate failed for %s", mint)
        state.log_event("error", wallet, mint, f"rug-gate error: {e}")
        return

    if not gate_result["pass"]:
        logger.info("rejected %s: %s", mint, gate_result["reasons"])
        state.log_event("rejected", wallet, mint, "; ".join(gate_result["reasons"]))
        return

    # Stage 2 — poll for momentum until Stage 3 timeout
    deadline = time.monotonic() + settings.MOMENTUM_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            momentum = await asyncio.to_thread(check_momentum, mint, wallet, insider_still_holding)
        except Exception as e:
            logger.exception("momentum-gate failed for %s", mint)
            state.log_event("error", wallet, mint, f"momentum-gate error: {e}")
            return

        if momentum["ready"]:
            data = await asyncio.to_thread(get_market_data, mint) or {}
            txns = (data.get("txns") or {}).get("m5") or {}
            ratio = f"{txns.get('buys', 0)}/{txns.get('sells', 0)}"
            try:
                send_alert(
                    mint=mint,
                    risk_score=gate_result.get("score", "n/a"),
                    buy_sell_ratio=ratio,
                    solscan_url=f"https://solscan.io/token/{mint}",
                )
            except Exception:
                logger.exception("telegram send failed for %s", mint)
            state.log_alert(mint, gate_result.get("score", "n/a"), ratio, wallet)
            state.log_event("cleared", wallet, mint, f"buy/sell {ratio}")
            logger.info("alert sent for %s", mint)
            return

        await asyncio.sleep(5)

    logger.info("hard abort on %s: momentum conditions not met in time", mint)
    state.log_event("abort", wallet, mint, "momentum conditions not met within timeout")
