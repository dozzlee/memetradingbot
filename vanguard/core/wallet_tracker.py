"""Real-time wallet monitor via Helius WebSocket `logsSubscribe` (PRD §2,
§7 — standard subscribe methods, free-tier compatible; NOT the paid
enhanced-websocket methods).

`logsSubscribe` with a `mentions` filter pushes a signature the instant a
tracked wallet is involved in a transaction. We then resolve that single
signature through Helius's Enhanced Transactions REST endpoint to get a
parsed `SWAP` with a clean `tokenTransfers` array, instead of hand-decoding
raw instruction logs. REST polling is used only as a fallback if the
WebSocket connection drops.
"""
import asyncio
import json
import logging

import requests
import websockets

from vanguard.config import settings
from vanguard.state import state

logger = logging.getLogger("wallet_tracker")

WS_URL = f"wss://mainnet.helius-rpc.com/?api-key={settings.HELIUS_API_KEY}"
PARSE_TX_URL = "https://api.helius.xyz/v0/transactions/"
TX_HISTORY_URL = "https://api.helius.xyz/v0/addresses/{wallet}/transactions"


def _parse_signature(signature: str) -> dict | None:
    resp = requests.post(
        PARSE_TX_URL,
        params={"api-key": settings.HELIUS_API_KEY},
        json={"transactions": [signature]},
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json()
    return results[0] if results else None


def _extract_buy_mint(tx: dict, wallet: str) -> str | None:
    if tx.get("type") != "SWAP":
        return None
    for transfer in tx.get("tokenTransfers", []):
        if transfer.get("toUserAccount") == wallet:
            return transfer.get("mint")
    return None


def _fetch_recent_transactions(wallet: str) -> list[dict]:
    resp = requests.get(
        TX_HISTORY_URL.format(wallet=wallet),
        params={"api-key": settings.HELIUS_API_KEY, "limit": 20},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def _handle_signature(wallet: str, signature: str, on_buy, seen: set):
    if signature in seen:
        return
    seen.add(signature)
    try:
        tx = await asyncio.to_thread(_parse_signature, signature)
    except requests.RequestException:
        logger.exception("failed to parse signature %s", signature)
        return
    if tx is None:
        return
    mint = _extract_buy_mint(tx, wallet)
    if mint:
        logger.info("%s bought %s (tx %s)", wallet, mint, signature)
        await on_buy(wallet, mint)


async def _run_websocket(on_buy, seen: set):
    """One WS connection subscribed to every tracked wallet via logsSubscribe.
    Reconnects (and re-subscribes to whatever's currently tracked) on drop."""
    async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=20) as ws:
        sub_id_to_wallet = {}
        for i, wallet in enumerate(state.tracked_wallets):
            await ws.send(json.dumps({
                "jsonrpc": "2.0", "id": i, "method": "logsSubscribe",
                "params": [{"mentions": [wallet]}, {"commitment": "confirmed"}],
            }))
            sub_id_to_wallet[i] = wallet  # request id, not subscription id
        logger.info("WS subscribed to %d wallet(s)", len(state.tracked_wallets))

        # Map JSON-RPC subscription ids (assigned in confirmations) to wallets.
        pending_confirms = dict(sub_id_to_wallet)
        subscription_to_wallet = {}

        async for raw in ws:
            msg = json.loads(raw)

            if "id" in msg and msg["id"] in pending_confirms:
                subscription_to_wallet[msg["result"]] = pending_confirms.pop(msg["id"])
                continue

            params = msg.get("params")
            if not params:
                continue
            sub_id = params.get("subscription")
            wallet = subscription_to_wallet.get(sub_id)
            if wallet is None:
                continue

            value = params.get("result", {}).get("value", {})
            if value.get("err") is not None:
                continue
            signature = value.get("signature")
            if signature:
                await _handle_signature(wallet, signature, on_buy, seen)

            # Wallets added at runtime after this connection opened aren't
            # subscribed yet — bail out so the caller reconnects and picks
            # them up. Cheap since reconnects are infrequent relative to
            # trading activity.
            if set(state.tracked_wallets) - set(subscription_to_wallet.values()):
                logger.info("tracked wallet set changed — reconnecting to resubscribe")
                return


async def _prime_seen(seen: set):
    """Seed `seen` with each wallet's most recent signature so we don't
    replay history through the WS path either."""
    for wallet in state.tracked_wallets:
        try:
            txs = await asyncio.to_thread(_fetch_recent_transactions, wallet)
            for tx in txs:
                seen.add(tx["signature"])
        except requests.RequestException:
            logger.exception("failed to prime baseline for %s", wallet)


async def watch_wallets(on_buy, poll_interval: int = 10):
    """on_buy(wallet: str, mint: str) is awaited whenever a tracked wallet
    buys a token. Primary path is the Helius WebSocket; falls back to REST
    polling if the socket can't connect or keeps dropping."""
    seen: set = set()
    await _prime_seen(seen)

    backoff = 1
    while True:
        try:
            await _run_websocket(on_buy, seen)
            backoff = 1  # clean reconnect (e.g. wallet list changed) — no backoff
        except (websockets.WebSocketException, OSError):
            logger.exception("WS connection dropped, falling back to REST poll for %ds", backoff)
            await asyncio.sleep(backoff)
            await _rest_poll_once(on_buy, seen)
            backoff = min(backoff * 2, 60)


async def _rest_poll_once(on_buy, seen: set):
    for wallet in state.tracked_wallets:
        try:
            txs = await asyncio.to_thread(_fetch_recent_transactions, wallet)
        except requests.RequestException:
            logger.exception("poll fallback failed for %s", wallet)
            continue
        for tx in reversed(txs):  # oldest first
            if tx["signature"] in seen:
                continue
            seen.add(tx["signature"])
            mint = _extract_buy_mint(tx, wallet)
            if mint:
                logger.info("%s bought %s (tx %s) [REST fallback]", wallet, mint, tx["signature"])
                await on_buy(wallet, mint)
