# Vanguard Protocol

Insider-cluster momentum intelligence engine for Solana memecoins. See
`docs/PRD.md` for the full spec (also at `Documents/Meme Trading/Vanguard_Protocol_PRD_v3.0.md`).

The bot only watches wallets, runs safety/momentum checks, and pushes
alerts to Telegram. It never holds keys or signs transactions — execution
is manual, via a third-party Telegram trading bot (Trojan, GMGN, etc.).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`:
- `HELIUS_API_KEY` — free tier is fine for tracking 5-10 wallets (see PRD §7)
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — a bot + private channel for alerts only
- `TRACKED_WALLETS` — comma-separated insider-cluster addresses (manual recon, PRD §3), optional at startup — you can add wallets from the dashboard instead

## Run

```bash
python -m vanguard.main
```

Opens a dashboard at `http://127.0.0.1:8000` — add/remove tracked wallets,
start/stop the monitor loop, and watch the decision log (buy detected →
rug-gate → momentum-gate → cleared/rejected/aborted) and cleared alerts
in real time. The monitor does not auto-start on boot; hit Start once
wallets are configured.

## Architecture

- `vanguard/core/wallet_tracker.py` — polls each tracked wallet's parsed
  transaction history via Helius's Enhanced Transactions API and detects
  `SWAP` buys. Polling instead of a raw WebSocket subscription because
  Helius already returns clean `tokenTransfers`, and polling works
  identically locally or on a VPS (a webhook would need a public endpoint).
- `vanguard/gates/rug_gate.py` — Stage 1 safety check via RugCheck.xyz.
  Excludes the token's own LP/bonding-curve account from top-holder
  concentration math (it isn't holder risk) and separately checks
  RugCheck's `insider`-flagged holders.
- `vanguard/gates/momentum_gate.py` — Stage 2 condition-based entry via
  DexScreener (basing, buy/sell ratio, liquidity, insider still holding).
- `vanguard/core/holdings.py` — the "insider still holding" check via
  Solana RPC `getTokenAccountsByOwner`.
- `vanguard/pipeline.py` — wires Stage 1 → 2 → 3 together and logs every
  decision to shared state.
- `vanguard/state.py` — in-memory state shared between the monitor loop
  and the dashboard (single process, single event loop — no DB/IPC).
- `vanguard/web/` — FastAPI app + static dashboard (`vanguard/web/static/index.html`).
- `vanguard/alerts/telegram_alert.py` — pushes cleared tokens to Telegram.

## Deploy (Netcup VPS)

Copy the repo to `/opt/vanguard`, install deps in a venv, then:

```bash
sudo cp deploy/vanguard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vanguard
```

Dashboard binds to `127.0.0.1:8000` by default — on a VPS you'd either
SSH-tunnel to it (`ssh -L 8000:localhost:8000 user@vps`) or put it behind
a reverse proxy with auth. It is not meant to be exposed publicly as-is.

## Known limitations / next steps

- **Honeypot / sell-route simulation is not implemented.** RugCheck's
  public report doesn't include it; a real check needs a funded wallet
  and a swap quote. Treat the rug-gate as necessary but not sufficient.
- **No persistence.** Alerts/events/tracked-wallets live in memory and
  reset on restart. Fine for a single-operator local/VPS setup; add
  SQLite if you want history across restarts.
- **Insider-cluster recon is still manual** (PRD §3) — the wallet in
  `.env` today is a placeholder for wiring/testing, not a vetted cluster
  wallet.
- **Thresholds are unvalidated heuristics** (PRD §9) — calibrate against
  logged outcomes before sizing up from $5.
