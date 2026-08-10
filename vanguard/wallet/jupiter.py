"""Swap execution via Jupiter's aggregator (quote + build + sign + send).
This is the only place in the codebase that produces a signed transaction —
signing happens in-memory with the keypair from vanguard/wallet/keystore.py
and the raw secret bytes never leave this call stack."""
import asyncio
import base64
import time

import requests
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

from vanguard.config import settings

QUOTE_URL = "https://quote-api.jup.ag/v6/quote"
SWAP_URL = "https://quote-api.jup.ag/v6/swap"


class SwapError(RuntimeError):
    pass


def get_quote(input_mint: str, output_mint: str, amount: int, slippage_bps: int) -> dict:
    """`amount` is in the input token's smallest unit (lamports for SOL)."""
    resp = requests.get(
        QUOTE_URL,
        params={
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": amount,
            "slippageBps": slippage_bps,
        },
        timeout=15,
    )
    resp.raise_for_status()
    quote = resp.json()
    if "outAmount" not in quote:
        raise SwapError(f"no route: {quote}")
    return quote


def _build_swap_transaction(quote: dict, user_pubkey: str) -> str:
    resp = requests.post(
        SWAP_URL,
        json={
            "quoteResponse": quote,
            "userPublicKey": user_pubkey,
            "wrapAndUnwrapSol": True,
            "dynamicComputeUnitLimit": True,
            "prioritizationFeeLamports": "auto",
        },
        timeout=15,
    )
    resp.raise_for_status()
    body = resp.json()
    if "swapTransaction" not in body:
        raise SwapError(f"swap build failed: {body}")
    return body["swapTransaction"]


def _sign(swap_tx_b64: str, keypair: Keypair) -> bytes:
    unsigned = VersionedTransaction.from_bytes(base64.b64decode(swap_tx_b64))
    signed = VersionedTransaction(unsigned.message, [keypair])
    return bytes(signed)


def _send_and_confirm(signed_tx_bytes: bytes, timeout_seconds: int = 60) -> str:
    b64_tx = base64.b64encode(signed_tx_bytes).decode()
    resp = requests.post(
        settings.HELIUS_RPC_URL,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [b64_tx, {"encoding": "base64", "skipPreflight": False, "maxRetries": 3}],
        },
        timeout=20,
    )
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        raise SwapError(f"sendTransaction failed: {body['error']}")
    signature = body["result"]

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status_resp = requests.post(
            settings.HELIUS_RPC_URL,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignatureStatuses",
                "params": [[signature]],
            },
            timeout=15,
        )
        status_resp.raise_for_status()
        value = (status_resp.json().get("result") or {}).get("value") or [None]
        status = value[0]
        if status is not None:
            if status.get("err"):
                raise SwapError(f"transaction {signature} failed on-chain: {status['err']}")
            if status.get("confirmationStatus") in ("confirmed", "finalized"):
                return signature
        time.sleep(2)

    raise SwapError(f"transaction {signature} not confirmed within {timeout_seconds}s")


def swap(input_mint: str, output_mint: str, amount: int, keypair: Keypair) -> tuple[str, int]:
    """Quotes, builds, signs, and sends a swap. Returns (signature, out_amount)
    where out_amount is in the output token's smallest unit — synchronous,
    call via asyncio.to_thread from async code."""
    quote = get_quote(input_mint, output_mint, amount, settings.SLIPPAGE_BPS)
    swap_tx_b64 = _build_swap_transaction(quote, str(keypair.pubkey()))
    signed_bytes = _sign(swap_tx_b64, keypair)
    signature = _send_and_confirm(signed_bytes)
    return signature, int(quote["outAmount"])


async def swap_async(input_mint: str, output_mint: str, amount: int, keypair: Keypair) -> tuple[str, int]:
    return await asyncio.to_thread(swap, input_mint, output_mint, amount, keypair)
