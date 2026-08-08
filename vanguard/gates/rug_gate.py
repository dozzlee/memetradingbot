"""Stage 1 — automated pre-buy safety check via RugCheck.xyz (PRD §5),
with an optional Solana Tracker cross-confirmation (PRD §5, "optional
second source")."""
import requests

from vanguard.config import settings

RUGCHECK_URL = "https://api.rugcheck.xyz/v1/tokens/{mint}/report"
SOLANA_TRACKER_URL = "https://data.solanatracker.io/tokens/{mint}"

# Honeypot / sell-route simulation isn't covered here — RugCheck's public
# report doesn't include it, and simulating a real sell needs a funded
# wallet + swap quote. Treat this gate as necessary but not sufficient.


def _cross_confirm(mint: str) -> list[str]:
    """Best-effort — only runs if SOLANA_TRACKER_API_KEY is set. Failures
    here should never block a trade on their own; RugCheck is primary."""
    if not settings.SOLANA_TRACKER_API_KEY:
        return []
    try:
        resp = requests.get(
            SOLANA_TRACKER_URL.format(mint=mint),
            headers={"x-api-key": settings.SOLANA_TRACKER_API_KEY},
            timeout=10,
        )
        resp.raise_for_status()
        risk = resp.json().get("risk", {})
    except requests.RequestException:
        return []

    reasons = []
    if risk.get("rugged"):
        reasons.append("Solana Tracker: flagged as rugged")
    score = risk.get("score")
    if isinstance(score, (int, float)) and score >= 7:
        reasons.append(f"Solana Tracker: danger score {score}/10")
    return reasons


def check_token(mint: str, top10_limit: int) -> dict:
    """Return {'pass': bool, 'reasons': [...], 'raw': {...}}."""
    resp = requests.get(RUGCHECK_URL.format(mint=mint), timeout=10)
    resp.raise_for_status()
    data = resp.json()

    reasons = []

    if data.get("token", {}).get("mintAuthority") is not None:
        reasons.append("mint authority not revoked")
    if data.get("freezeAuthority") is not None:
        reasons.append("freeze authority active")

    markets = data.get("markets") or []
    lp_locked_pct = max((m.get("lp", {}).get("lpLockedPct", 0) for m in markets), default=0)
    if lp_locked_pct < 80:
        reasons.append(f"LP not sufficiently locked/burned ({lp_locked_pct:.0f}%)")

    # Exclude the LP/bonding-curve account itself — it legitimately holds a
    # large share pre-graduation and isn't holder concentration risk.
    lp_addresses = {m.get("pubkey") for m in markets if m.get("pubkey")}
    real_holders = [
        h for h in (data.get("topHolders") or [])
        if h.get("owner") not in lp_addresses and h.get("address") not in lp_addresses
    ]
    top10_pct = sum(h.get("pct", 0) for h in real_holders[:10])
    if top10_pct > top10_limit:
        reasons.append(f"top-10 concentration {top10_pct:.1f}% > {top10_limit}%")

    insider_pct = sum(h.get("pct", 0) for h in (data.get("topHolders") or []) if h.get("insider"))
    if insider_pct > top10_limit:
        reasons.append(f"insider-network holdings {insider_pct:.1f}% > {top10_limit}%")

    if data.get("rugged", False):
        reasons.append("already flagged as rugged")

    for risk in data.get("risks") or []:
        if risk.get("level") in ("danger", "high"):
            reasons.append(f"RugCheck risk: {risk.get('name')}")

    reasons.extend(_cross_confirm(mint))

    return {
        "pass": len(reasons) == 0,
        "reasons": reasons,
        "score": data.get("score_normalised"),
        "raw": data,
    }
