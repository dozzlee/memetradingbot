"""Stage 2 — condition-based entry check via DexScreener (PRD §4)."""
import requests

from vanguard.config import settings

DEXSCREENER_URL = "https://api.dexscreener.com/latest/dex/tokens/{mint}"

# Per-mint rolling price samples so "basing, not bleeding" is judged from
# what this token is actually doing sample-to-sample during our own polling
# window, not just the sign of DexScreener's fixed 5-minute window (which
# stays negative for a while after a real bottom).
_price_history: dict[str, list[tuple[float, float]]] = {}


def get_market_data(mint: str) -> dict | None:
    resp = requests.get(DEXSCREENER_URL.format(mint=mint), timeout=10)
    resp.raise_for_status()
    pairs = resp.json().get("pairs") or []
    return pairs[0] if pairs else None


def _record_price(mint: str, price_usd: float) -> list[float]:
    import time
    hist = _price_history.setdefault(mint, [])
    hist.append((time.monotonic(), price_usd))
    del hist[:-6]  # keep last 6 samples
    return [p for _, p in hist]


def _is_basing(prices: list[float], fallback_change_m5: float) -> bool:
    if len(prices) < 3:
        # Not enough local samples yet — fall back to DexScreener's window.
        return fallback_change_m5 >= -2
    recent = prices[-3:]
    # Basing if the most recent sample isn't a new local low by more than
    # a small margin — i.e. price has stopped making lower lows.
    return recent[-1] >= min(recent[:-1]) * 0.98


def check_momentum(mint: str, insider_wallet: str, insider_still_holding_fn) -> dict:
    """Return {'ready': bool, 'reasons': [...]}. Caller polls this on a loop
    for up to MOMENTUM_TIMEOUT_SECONDS (Stage 3 hard abort)."""
    data = get_market_data(mint)
    if data is None:
        return {"ready": False, "reasons": ["no market data yet"]}

    reasons = []

    price_usd = float(data.get("priceUsd") or 0)
    prices = _record_price(mint, price_usd) if price_usd else []
    price_change_m5 = (data.get("priceChange") or {}).get("m5", 0)
    if not _is_basing(prices, price_change_m5):
        reasons.append("still bleeding, not basing")

    txns_m5 = (data.get("txns") or {}).get("m5") or {}
    buys = txns_m5.get("buys", 0)
    sells = txns_m5.get("sells", 0)
    if sells and buys / max(sells, 1) < 1.0:
        reasons.append("buy/sell ratio not net-positive")

    # pump.fun pairs pre-graduation report no `liquidity` block (bonding
    # curve, not an LP) — only require this check once liquidity is reported.
    liquidity = data.get("liquidity")
    if liquidity is not None and liquidity.get("usd", 0) <= 0:
        reasons.append("no liquidity / LP pulled")

    graduated = data.get("dexId") != "pumpfun"
    if settings.REQUIRE_PUMPFUN_GRADUATION and not graduated:
        reasons.append("has not graduated off pump.fun bonding curve yet")

    if not insider_still_holding_fn(insider_wallet, mint):
        reasons.append("insider sold — abort (decoy/rug)")

    return {
        "ready": len(reasons) == 0,
        "reasons": reasons,
        "raw": data,
        "graduated": graduated,
    }
