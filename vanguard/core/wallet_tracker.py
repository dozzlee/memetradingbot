"""WebSocket listener on tracked insider-cluster wallets via Helius (PRD §2, §7).

Uses standard accountSubscribe (free-tier compatible) — NOT the enhanced
subscribe methods, which require a paid Helius Developer plan.
"""
import asyncio
import json
import logging

import websockets

from vanguard.config import settings

logger = logging.getLogger("wallet_tracker")


async def watch_wallets(on_buy):
    """on_buy(wallet: str, mint: str) is called whenever a tracked wallet buys a token."""
    async with websockets.connect(settings.HELIUS_WS_URL) as ws:
        for i, wallet in enumerate(settings.TRACKED_WALLETS):
            sub = {
                "jsonrpc": "2.0",
                "id": i,
                "method": "accountSubscribe",
                "params": [wallet, {"encoding": "jsonParsed", "commitment": "confirmed"}],
            }
            await ws.send(json.dumps(sub))
            logger.info("subscribed to %s", wallet)

        async for message in ws:
            msg = json.loads(message)
            # TODO: parse account update, detect new-token buy, resolve mint address
            # then: await on_buy(wallet, mint)
            logger.debug("account update: %s", msg)
