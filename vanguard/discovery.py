"""Automated wallet-discovery system: finds candidate copy-trading wallets
without you having to manually pick a developer first (that manual,
single-dev flow — PRD §3 — still exists as `scripts/find_cluster.py` for
when you already have one in mind).

Method: pull a pool of currently-prominent Solana tokens (DexScreener's
boosted + community-submitted profile feeds — the closest thing to "which
tokens are getting real attention right now" available without a paid
data API), keep the ones above a market-cap floor and old enough to have
a settled early-buyer history, then pull each one's first N buyers via
Helius and rank wallets by how many *different* successful tokens they
were early on.

This is a broader "smart early money" signal than the PRD's narrower
single-developer cluster method — it doesn't confirm these wallets share
a developer, only that they're consistently early into things that went
on to do real volume. Treat a high hit-count as a strong reason to look
closer (put it through `backtest_wallet`), not as an auto-add.
"""
import logging
import time
from collections import defaultdict

import requests

from vanguard.config import settings
from vanguard.gates.momentum_gate import get_market_data

logger = logging.getLogger("discovery")

BOOSTS_TOP_URL = "https://api.dexscreener.com/token-boosts/top/v1"
BOOSTS_LATEST_URL = "https://api.dexscreener.com/token-boosts/latest/v1"
PROFILES_URL = "https://api.dexscreener.com/token-profiles/latest/v1"
SOLANA_TRACKER_TRENDING_URL = "https://data.solanatracker.io/tokens/trending"
SEARCH_URL = "https://api.dexscreener.com/latest/dex/search"
# Broad terms to pull real, currently-liquid Solana pairs into the candidate
# pool — the boosts/profiles feeds skew toward brand-new low-cap tokens
# (people paying to promote something that just launched), so on their own
# they rarely surface enough $1M+ survivors to find overlap between.
SEARCH_TERMS = ["pump", "solana", "bonk", "moon", "cat", "dog", "ai"]
TX_URL = "https://api.helius.xyz/v0/addresses/{mint}/transactions"

MIN_AGE_SECONDS = 30 * 60  # needs a settled-enough history to have real "early" buyers
# "Early buyers" only means something for a token that recently launched —
# walking back 300 txs on a token that's been trading for months/years just
# surfaces random recent traders, not insiders. Caps the pool to genuinely
# recent launches, matching the PRD's actual target (new pump.fun tokens).
MAX_AGE_SECONDS = 90 * 24 * 60 * 60
EARLY_BUYERS_PER_TOKEN = 10
MAX_PAGES = 3

# Established infra/majors that show up in keyword search results but are
# not memecoin launches — including them would poison the "early buyer"
# signal (see MAX_AGE_SECONDS above; this is a belt-and-suspenders blocklist
# for majors whose age alone might not exclude them, e.g. a new wrapped
# variant).
EXCLUDED_SYMBOLS = {"SOL", "WSOL", "USDC", "USDT", "BONK", "PUMP", "ETH", "WBTC", "JUP", "JTO"}


def _candidate_mints() -> list[str]:
    mints = set()
    for url in (BOOSTS_TOP_URL, BOOSTS_LATEST_URL, PROFILES_URL):
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            for item in resp.json():
                if item.get("chainId") == "solana" and item.get("tokenAddress"):
                    mints.add(item["tokenAddress"])
        except requests.RequestException:
            logger.exception("failed to fetch candidate feed %s", url)

    for term in SEARCH_TERMS:
        try:
            resp = requests.get(SEARCH_URL, params={"q": term}, timeout=10)
            resp.raise_for_status()
            for pair in resp.json().get("pairs") or []:
                if pair.get("chainId") == "solana":
                    mints.add(pair["baseToken"]["address"])
        except (requests.RequestException, KeyError):
            logger.exception("failed to fetch search candidates for %r", term)

    # Wider, higher-quality pool if a Solana Tracker key is configured
    # (PRD §5's "optional second source") — free tier requires a key even
    # for trending, so this only fires once one's set.
    if settings.SOLANA_TRACKER_API_KEY:
        try:
            resp = requests.get(
                SOLANA_TRACKER_TRENDING_URL,
                headers={"x-api-key": settings.SOLANA_TRACKER_API_KEY},
                timeout=10,
            )
            resp.raise_for_status()
            for item in resp.json():
                mint = (item.get("token") or {}).get("mint") or item.get("mint")
                if mint:
                    mints.add(mint)
        except requests.RequestException:
            logger.exception("failed to fetch Solana Tracker trending feed")

    return list(mints)


def _qualify(mint: str, min_mcap: float) -> dict | None:
    try:
        data = get_market_data(mint)
    except requests.RequestException:
        return None
    if not data:
        return None

    symbol = data.get("baseToken", {}).get("symbol", "?")
    if symbol.upper() in EXCLUDED_SYMBOLS:
        return None

    mcap = data.get("marketCap") or data.get("fdv") or 0
    created = data.get("pairCreatedAt")
    if mcap < min_mcap:
        return None
    if created:
        age = time.time() - created / 1000
        if age < MIN_AGE_SECONDS:
            return None  # too fresh — "early buyers" wouldn't mean much yet
        if age > MAX_AGE_SECONDS:
            return None  # too old — can't reach genesis buyers by paginating back
    else:
        return None  # no creation timestamp, can't judge age — skip rather than guess

    return {
        "mint": mint,
        "symbol": symbol,
        "market_cap": mcap,
    }


def _early_buyers(mint: str) -> list[str]:
    all_txs = []
    before = None
    for _ in range(MAX_PAGES):
        params = {"api-key": settings.HELIUS_API_KEY, "type": "SWAP", "limit": 100}
        if before:
            params["before"] = before
        try:
            resp = requests.get(TX_URL.format(mint=mint), params=params, timeout=15)
            resp.raise_for_status()
        except requests.RequestException:
            break
        page = resp.json()
        if not page:
            break
        all_txs.extend(page)
        before = page[-1]["signature"]
        if len(page) < 100:
            break

    all_txs.sort(key=lambda tx: tx.get("timestamp", 0))
    buyers, seen = [], set()
    for tx in all_txs:
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


def discover_wallets(min_mcap: float = 1_000_000, max_tokens: int = 12) -> dict:
    candidates = _candidate_mints()
    qualified = []
    for mint in candidates:
        q = _qualify(mint, min_mcap)
        if q:
            qualified.append(q)
    qualified.sort(key=lambda q: -q["market_cap"])
    qualified = qualified[:max_tokens]

    wallet_hits: dict[str, list[dict]] = defaultdict(list)
    scanned = []
    for token in qualified:
        buyers = _early_buyers(token["mint"])
        scanned.append({**token, "early_buyers_found": len(buyers)})
        for w in buyers:
            wallet_hits[w].append(token)

    ranked = [
        {"address": w, "hit_count": len(tokens), "tokens": tokens}
        for w, tokens in wallet_hits.items()
        if len(tokens) >= 2  # appearing early on just one token is not a signal
    ]
    ranked.sort(key=lambda r: (-r["hit_count"], -sum(t["market_cap"] for t in r["tokens"])))

    return {"scanned_tokens": scanned, "wallets": ranked}
