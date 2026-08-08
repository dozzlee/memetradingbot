#!/usr/bin/env python3
"""Insider-cluster recon helper (PRD §3) — partially automates the manual
step: given 3+ past token mints from the same developer, find wallets that
appear among the first buyers of ALL of them.

This does NOT identify the developer's launches for you — you still supply
those mints yourself (Solscan/Bubblemaps/pump.fun creator history). What it
automates is the tedious "pull first ~10 buyers, diff the lists" part.

Usage:
    python scripts/find_cluster.py <HELIUS_API_KEY> <mint1> <mint2> <mint3> [...]
"""
import sys
from collections import defaultdict

import requests

TX_URL = "https://api.helius.xyz/v0/addresses/{mint}/transactions"
EARLY_BUYERS_PER_TOKEN = 10
MAX_PAGES = 5  # 5 * 100 = 500 txs of history walked per token


def fetch_all_swaps(mint: str, api_key: str) -> list[dict]:
    """Walk transaction history backwards (toward token genesis) collecting
    SWAP txs, since getting the *earliest* buyers means paginating past
    whatever trading has happened since."""
    all_txs = []
    before = None
    for _ in range(MAX_PAGES):
        params = {"api-key": api_key, "limit": 100}
        if before:
            params["before"] = before
        resp = requests.get(TX_URL.format(mint=mint), params=params, timeout=15)
        resp.raise_for_status()
        page = resp.json()
        if not page:
            break
        all_txs.extend(page)
        before = page[-1]["signature"]
        if len(page) < 100:
            break
    return all_txs


def early_buyers(mint: str, api_key: str) -> list[str]:
    txs = fetch_all_swaps(mint, api_key)
    swaps = [tx for tx in txs if tx.get("type") == "SWAP"]
    swaps.sort(key=lambda tx: tx.get("timestamp", 0))  # oldest first

    buyers = []
    seen = set()
    for tx in swaps:
        for transfer in tx.get("tokenTransfers", []):
            if transfer.get("mint") != mint:
                continue
            buyer = transfer.get("toUserAccount")
            if buyer and buyer not in seen:
                seen.add(buyer)
                buyers.append(buyer)
        if len(buyers) >= EARLY_BUYERS_PER_TOKEN:
            break
    return buyers[:EARLY_BUYERS_PER_TOKEN]


def main():
    if len(sys.argv) < 5:
        print(__doc__)
        sys.exit(1)

    api_key = sys.argv[1]
    mints = sys.argv[2:]

    buyer_sets = {}
    for mint in mints:
        print(f"Fetching early buyers for {mint}...", file=sys.stderr)
        buyers = early_buyers(mint, api_key)
        buyer_sets[mint] = set(buyers)
        print(f"  {len(buyers)} early buyers found", file=sys.stderr)

    counts = defaultdict(int)
    for wallets in buyer_sets.values():
        for w in wallets:
            counts[w] += 1

    all_overlap = sorted(w for w, c in counts.items() if c == len(mints))
    partial_overlap = sorted((w, c) for w, c in counts.items() if 1 < c < len(mints))

    print(f"\n=== Wallets in ALL {len(mints)} launches (highest-confidence cluster) ===")
    for w in all_overlap:
        print(w)
    if not all_overlap:
        print("(none)")

    print(f"\n=== Wallets in 2+ but not all launches (weaker signal) ===")
    for w, c in sorted(partial_overlap, key=lambda x: -x[1]):
        print(f"{w}  ({c}/{len(mints)})")
    if not partial_overlap:
        print("(none)")


if __name__ == "__main__":
    main()
