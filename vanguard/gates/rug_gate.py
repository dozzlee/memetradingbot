"""Stage 1 — automated pre-buy safety check via RugCheck.xyz (PRD §5)."""
import requests

RUGCHECK_URL = "https://api.rugcheck.xyz/v1/tokens/{mint}/report"


def check_token(mint: str, top10_limit: int) -> dict:
    """Return {'pass': bool, 'reasons': [...], 'raw': {...}}."""
    resp = requests.get(RUGCHECK_URL.format(mint=mint), timeout=10)
    resp.raise_for_status()
    data = resp.json()

    reasons = []

    if not data.get("mintAuthorityRevoked", False):
        reasons.append("mint authority not revoked")
    if data.get("freezeAuthority"):
        reasons.append("freeze authority active")
    if not data.get("lpBurnedOrLocked", False):
        reasons.append("LP not burned or locked")
    if not data.get("sellRouteOk", True):
        reasons.append("no working sell route / honeypot")
    if data.get("top10HolderPct", 0) > top10_limit:
        reasons.append(f"top-10 concentration above {top10_limit}%")
    if data.get("rugged", False):
        reasons.append("already flagged as rugged")

    return {"pass": len(reasons) == 0, "reasons": reasons, "raw": data}
