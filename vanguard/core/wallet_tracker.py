"""Poll tracked insider-cluster wallets via Helius's Enhanced Transactions
API and detect SWAP buys (PRD §2, §7).

Polling (not raw accountSubscribe) because Helius returns fully-parsed
SWAP transactions with a clean tokenTransfers array — no need to decode
raw account diffs ourselves. Works identically locally or on the VPS,
unlike a webhook, which needs a public HTTPS endpoint.
"""
import asyncio
import logging

import requests

from vanguard.config import settings
from vanguard.state import state

logger = logging.getLogger("wallet_tracker")

TX_URL = "https://api.helius.xyz/v0/addresses/{wallet}/transactions"


def _fetch_transactions(wallet: str, before: str | None = None) -> list[dict]:
    params = {"api-key": settings.HELIUS_API_KEY, "limit": 20}
    if before:
        params["before"] = before
    resp = requests.get(TX_URL.format(wallet=wallet), params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _extract_buy_mint(tx: dict, wallet: str) -> str | None:
    if tx.get("type") != "SWAP":
        return None
    for transfer in tx.get("tokenTransfers", []):
        if transfer.get("toUserAccount") == wallet:
            return transfer.get("mint")
    return None


async def _prime_baseline(wallet: str, last_seen: dict):
    try:
        txs = await asyncio.to_thread(_fetch_transactions, wallet)
        last_seen[wallet] = txs[0]["signature"] if txs else None
        logger.info("watching %s (baseline: %s)", wallet, last_seen[wallet])
    except requests.RequestException:
        logger.exception("failed to prime baseline for %s", wallet)
        last_seen[wallet] = None


async def watch_wallets(on_buy, poll_interval: int = 10):
    """on_buy(wallet: str, mint: str) is awaited whenever a tracked wallet
    buys a token. Polls each wallet's transaction history on a loop.

    Reads state.tracked_wallets each iteration so wallets can be added or
    removed at runtime (via the dashboard) without restarting the process.
    """
    last_seen: dict[str, str | None] = {}
    for wallet in state.tracked_wallets:
        await _prime_baseline(wallet, last_seen)

    while True:
        # Pick up wallets added at runtime; prime them so we don't replay history.
        for wallet in state.tracked_wallets:
            if wallet not in last_seen:
                await _prime_baseline(wallet, last_seen)
        # Drop wallets removed at runtime.
        for wallet in list(last_seen):
            if wallet not in state.tracked_wallets:
                del last_seen[wallet]

        for wallet in state.tracked_wallets:
            try:
                txs = await asyncio.to_thread(_fetch_transactions, wallet)
            except requests.RequestException:
                logger.exception("poll failed for %s", wallet)
                continue

            new_txs = []
            for tx in txs:
                if tx["signature"] == last_seen[wallet]:
                    break
                new_txs.append(tx)

            if new_txs:
                last_seen[wallet] = new_txs[0]["signature"]

            for tx in reversed(new_txs):  # oldest first
                mint = _extract_buy_mint(tx, wallet)
                if mint:
                    logger.info("%s bought %s (tx %s)", wallet, mint, tx["signature"])
                    await on_buy(wallet, mint)

        await asyncio.sleep(poll_interval)
