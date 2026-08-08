import asyncio
import logging
import time

from vanguard.config import settings
from vanguard.core.wallet_tracker import watch_wallets
from vanguard.gates.rug_gate import check_token
from vanguard.gates.momentum_gate import check_momentum, get_market_data
from vanguard.alerts.telegram_alert import send_alert

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vanguard")


def insider_still_holding(wallet: str, mint: str) -> bool:
    # TODO: check wallet's current token balance for `mint` via Helius/RPC
    return True


async def on_buy(wallet: str, mint: str):
    logger.info("tracked wallet %s bought %s — running rug-gate", wallet, mint)

    # Stage 1 — safety window
    await asyncio.sleep(settings.SAFETY_WINDOW_SECONDS)
    gate_result = check_token(mint, settings.TOP10_CONCENTRATION_LIMIT)
    if not gate_result["pass"]:
        logger.info("rejected %s: %s", mint, gate_result["reasons"])
        return

    # Stage 2 — poll for momentum until Stage 3 timeout
    deadline = time.monotonic() + settings.MOMENTUM_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        momentum = check_momentum(mint, wallet, insider_still_holding)
        if momentum["ready"]:
            data = get_market_data(mint) or {}
            txns = data.get("txns", {}).get("m5", {})
            ratio = f"{txns.get('buys', 0)}/{txns.get('sells', 0)}"
            send_alert(
                mint=mint,
                risk_score=gate_result["raw"].get("score", "n/a"),
                buy_sell_ratio=ratio,
                solscan_url=f"https://solscan.io/token/{mint}",
            )
            logger.info("alert sent for %s", mint)
            return
        await asyncio.sleep(5)

    logger.info("hard abort on %s: momentum conditions not met in time", mint)


async def main():
    if not settings.TRACKED_WALLETS:
        raise SystemExit("TRACKED_WALLETS is empty — add insider-cluster addresses to .env")
    await watch_wallets(on_buy)


if __name__ == "__main__":
    asyncio.run(main())
