"""Check whether a tracked wallet still holds a given mint (PRD §4 Stage 2:
'insider still holding' check)."""
import requests

from vanguard.config import settings


def insider_still_holding(wallet: str, mint: str) -> bool:
    resp = requests.post(
        settings.HELIUS_RPC_URL,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [wallet, {"mint": mint}, {"encoding": "jsonParsed"}],
        },
        timeout=10,
    )
    resp.raise_for_status()
    accounts = resp.json().get("result", {}).get("value", [])
    for acct in accounts:
        amount = acct["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"]
        if amount and amount > 0:
            return True
    return False
