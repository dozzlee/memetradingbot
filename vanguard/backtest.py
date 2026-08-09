"""Two analysis tools that don't require the wallet to be funded:

1. `inspect_token` — run the same rug-gate + momentum-gate checks the live
   pipeline uses, on demand, against any mint. This is the "should I get
   this coin" button for the dashboard.

2. `backtest_wallet` — pull a tracked wallet's past SWAP buys from Helius,
   and for each one compute what would have happened if you'd copied it:
   current value of the tokens received vs. SOL spent, plus whether the
   rug-gate would reject the token *today*.

Honest limitation: DexScreener has no historical OHLC endpoint on the free
tier, so this is NOT a tick-by-tick replay of the momentum gate at the
exact historical entry time — it can't tell you whether Stage 2 would have
fired. What it tells you is (a) whether copying this wallet's past buys
would have been profitable holding to now, which validates whether the
wallet is worth tracking at all (PRD §3/§9 calibration), and (b) whether
each token would pass today's rug-gate, as a rough proxy for how many of
this wallet's picks were/are scams. Returns are computed in SOL terms
(tokens_now * current priceNative vs sol_spent) specifically to avoid
needing a historical SOL/USD rate we don't have.
"""
import logging

import requests

from vanguard.config import settings
from vanguard.gates import rug_gate, momentum_gate

logger = logging.getLogger("backtest")

SOL_MINT = "So11111111111111111111111111111111111111112"
TX_HISTORY_URL = "https://api.helius.xyz/v0/addresses/{wallet}/transactions"

# Majors/stables swapped for SOL aren't memecoin "buys" in the sense this
# tool cares about, and their price moves with SOL itself, which produces
# nonsense SOL-denominated "returns". Excluded from buy detection.
EXCLUDED_MINTS = {
    SOL_MINT,
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
}


def inspect_token(mint: str) -> dict:
    """On-demand Stage-1 + Stage-2 analysis for a single mint, without
    waiting for a tracked-wallet buy to trigger it."""
    result = {"mint": mint}

    try:
        result["rug_gate"] = rug_gate.check_token(mint, settings.TOP10_CONCENTRATION_LIMIT)
    except requests.RequestException as e:
        result["rug_gate"] = {"pass": None, "reasons": [f"RugCheck lookup failed: {e}"]}

    try:
        result["momentum"] = momentum_gate.check_momentum(mint, "", lambda w, m: True)
        # insider-holding is meaningless without a specific wallet — drop that reason
        result["momentum"]["reasons"] = [
            r for r in result["momentum"]["reasons"] if "insider sold" not in r
        ]
        result["momentum"]["ready"] = len(result["momentum"]["reasons"]) == 0
    except requests.RequestException as e:
        result["momentum"] = {"ready": None, "reasons": [f"DexScreener lookup failed: {e}"]}

    return result


def _fetch_swap_history(wallet: str, limit: int) -> list[dict]:
    resp = requests.get(
        TX_HISTORY_URL.format(wallet=wallet),
        params={"api-key": settings.HELIUS_API_KEY, "type": "SWAP", "limit": limit},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _extract_buy(tx: dict, wallet: str) -> dict | None:
    transfers = tx.get("tokenTransfers") or []
    received = [
        t for t in transfers
        if t.get("toUserAccount") == wallet and t.get("mint") not in EXCLUDED_MINTS
    ]
    sol_spent = sum(
        t.get("tokenAmount", 0) for t in transfers
        if t.get("fromUserAccount") == wallet and t.get("mint") == SOL_MINT
    )
    if not received or sol_spent <= 0:
        return None
    # A swap can list the same mint split across multiple transfer legs.
    mint = received[0]["mint"]
    tokens_received = sum(t.get("tokenAmount", 0) for t in received if t.get("mint") == mint)
    return {
        "mint": mint,
        "tokens_received": tokens_received,
        "sol_spent": sol_spent,
        "timestamp": tx.get("timestamp"),
        "signature": tx.get("signature"),
    }


def backtest_wallet(wallet: str, max_buys: int = 20) -> dict:
    try:
        txs = _fetch_swap_history(wallet, limit=100)
    except requests.RequestException as e:
        return {"wallet": wallet, "error": str(e), "trades": []}

    buys = []
    for tx in txs:
        buy = _extract_buy(tx, wallet)
        if buy:
            buys.append(buy)
        if len(buys) >= max_buys:
            break

    trades = []
    for buy in buys:
        entry = dict(buy)
        try:
            data = momentum_gate.get_market_data(buy["mint"])
        except requests.RequestException:
            data = None

        if data:
            price_native = float(data.get("priceNative") or 0)
            price_usd = float(data.get("priceUsd") or 0)
            current_value_sol = buy["tokens_received"] * price_native
            entry["current_price_usd"] = price_usd
            entry["multiple"] = (current_value_sol / buy["sol_spent"]) if buy["sol_spent"] else None
            entry["return_pct"] = ((entry["multiple"] - 1) * 100) if entry["multiple"] is not None else None
        else:
            entry["current_price_usd"] = None
            entry["multiple"] = None
            entry["return_pct"] = None
            entry["note"] = "no current market data (likely delisted/dead)"

        try:
            gate = rug_gate.check_token(buy["mint"], settings.TOP10_CONCENTRATION_LIMIT)
            entry["would_pass_gate_today"] = gate["pass"]
        except requests.RequestException:
            entry["would_pass_gate_today"] = None

        trades.append(entry)

    evaluable = [t for t in trades if t["return_pct"] is not None]
    wins = [t for t in evaluable if t["return_pct"] > 0]

    summary = {
        "wallet": wallet,
        "buys_found": len(trades),
        "evaluable": len(evaluable),
        "win_rate_pct": round(100 * len(wins) / len(evaluable), 1) if evaluable else None,
        "avg_return_pct": round(sum(t["return_pct"] for t in evaluable) / len(evaluable), 1) if evaluable else None,
        "would_pass_gate_today_count": sum(1 for t in trades if t.get("would_pass_gate_today")),
        "trades": trades,
    }
    return summary
