"""SOL/USD price lookup, used both for dashboard balance display and for
sizing swaps (converting a fixed USD position size into lamports)."""
import requests

SOL_MINT = "So11111111111111111111111111111111111111112"
JUPITER_PRICE_URL = "https://api.jup.ag/price/v2"


def get_sol_price_usd() -> float:
    resp = requests.get(JUPITER_PRICE_URL, params={"ids": SOL_MINT}, timeout=10)
    resp.raise_for_status()
    data = resp.json().get("data") or {}
    entry = data.get(SOL_MINT) or {}
    price = entry.get("price")
    if not price:
        raise RuntimeError("Jupiter price API returned no SOL price")
    return float(price)
