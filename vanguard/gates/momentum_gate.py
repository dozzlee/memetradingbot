"""Stage 2 — condition-based entry check via DexScreener (PRD §4)."""
import requests

DEXSCREENER_URL = "https://api.dexscreener.com/latest/dex/tokens/{mint}"


def get_market_data(mint: str) -> dict | None:
    resp = requests.get(DEXSCREENER_URL.format(mint=mint), timeout=10)
    resp.raise_for_status()
    pairs = resp.json().get("pairs") or []
    return pairs[0] if pairs else None


def check_momentum(mint: str, insider_wallet: str, insider_still_holding_fn) -> dict:
    """Return {'ready': bool, 'reasons': [...]}. Caller polls this on a loop
    for up to MOMENTUM_TIMEOUT_SECONDS (Stage 3 hard abort)."""
    data = get_market_data(mint)
    if data is None:
        return {"ready": False, "reasons": ["no market data yet"]}

    reasons = []

    price_change_m5 = data.get("priceChange", {}).get("m5", 0)
    if price_change_m5 < -2:
        reasons.append("still bleeding, not basing")

    buys = data.get("txns", {}).get("m5", {}).get("buys", 0)
    sells = data.get("txns", {}).get("m5", {}).get("sells", 0)
    if sells and buys / max(sells, 1) < 1.0:
        reasons.append("buy/sell ratio not net-positive")

    liquidity_usd = data.get("liquidity", {}).get("usd", 0)
    if liquidity_usd <= 0:
        reasons.append("no liquidity data / LP pulled")

    if not insider_still_holding_fn(insider_wallet, mint):
        reasons.append("insider sold — abort (decoy/rug)")

    return {"ready": len(reasons) == 0, "reasons": reasons, "raw": data}
