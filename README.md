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
- `SOLANA_TRACKER_API_KEY` — optional, enables cross-confirmation in the rug-gate (PRD §5)
- `REQUIRE_PUMPFUN_GRADUATION` — optional, defaults off (see rationale in `vanguard/config/settings.py`)

## Run

```bash
python -m vanguard.main
```

Opens a dashboard at `http://127.0.0.1:8000`:
- add/remove tracked wallets, start/stop the monitor loop
- live decision log (buy detected → rug-gate → momentum-gate → cleared/rejected/aborted)
- cleared alerts table
- a manual trade ledger — since the bot never executes trades itself, log
  what you actually did in the execution bot (entry price, size, exit,
  fees) and it computes P&L/outcome, for calibrating thresholds later

The monitor does not auto-start on boot; hit Start once wallets are configured.
Tracked wallets and all history persist in `vanguard.db` (SQLite) across restarts.

## Architecture

- `vanguard/core/wallet_tracker.py` — real-time wallet monitor via Helius's
  `logsSubscribe` WebSocket (PRD §2/§7, standard free-tier method). On a
  matching signature, resolves it through Helius's Enhanced Transactions
  REST endpoint (one signature at a time) to get a parsed `SWAP` with a
  clean `tokenTransfers` array, instead of hand-decoding raw logs. Falls
  back to REST polling with exponential backoff if the socket drops.
- `vanguard/gates/rug_gate.py` — Stage 1 safety check via RugCheck.xyz,
  with optional Solana Tracker cross-confirmation. Excludes the token's
  own LP/bonding-curve account from top-holder concentration math (it
  isn't holder risk) and separately checks RugCheck's `insider`-flagged
  holders.
- `vanguard/gates/momentum_gate.py` — Stage 2 condition-based entry via
  DexScreener. "Basing, not bleeding" is judged from our own rolling
  price samples during the polling window (not just the sign of
  DexScreener's fixed 5-minute change, which stays negative well past a
  real bottom). Also surfaces pump.fun graduation status.
- `vanguard/core/holdings.py` — the "insider still holding" check via
  Solana RPC `getTokenAccountsByOwner`.
- `vanguard/pipeline.py` — wires Stage 1 → 2 → 3 together and logs every
  decision to shared state.
- `vanguard/db.py` / `vanguard/state.py` — SQLite persistence (wallets,
  decision events, alerts, trade ledger) behind a small in-process state
  object shared by the monitor loop and the dashboard.
- `vanguard/web/` — FastAPI app + static dashboard (`vanguard/web/static/index.html`).
- `vanguard/alerts/telegram_alert.py` — pushes cleared tokens to Telegram.
- `scripts/find_cluster.py` — insider-cluster recon helper (PRD §3): given
  3+ past token mints from the same developer, pulls each token's early
  buyers via Helius and reports wallets that overlap across all of them.
  Doesn't find the developer's launches for you — that part's still manual.

## Deploy (Netcup VPS)

```bash
sudo bash deploy/harden.sh   # SSH key-only auth, ufw, unattended-upgrades — run once, see script header
sudo cp deploy/vanguard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vanguard
```

Dashboard binds to `127.0.0.1:8000` by default — on a VPS you'd either
SSH-tunnel to it (`ssh -L 8000:localhost:8000 vanguard@vps`) or put it
behind a reverse proxy with auth. It is not meant to be exposed publicly as-is.

## Known limitations / next steps

- **Honeypot / sell-route simulation is not implemented.** RugCheck's
  public report doesn't include it; a real check needs a funded wallet
  and a swap quote. Treat the rug-gate as necessary but not sufficient.
- **Insider-cluster recon is still partly manual** (PRD §3) —
  `scripts/find_cluster.py` automates the overlap-diffing step, but you
  still have to find and supply the developer's past launch mints. The
  wallet seeded in `.env` today is a placeholder for wiring/testing, not
  a vetted cluster wallet.
- **Thresholds are unvalidated heuristics** (PRD §9) — calibrate against
  the trade ledger's logged outcomes before sizing up from $5.
- **Solana Tracker cross-confirmation is untested end-to-end** — wired in
  and no-ops cleanly without a key, but hasn't been verified against a
  live `SOLANA_TRACKER_API_KEY` (none was available while building this).
