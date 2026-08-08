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
- `TRACKED_WALLETS` — comma-separated insider-cluster addresses (manual recon, PRD §3)

## Run

```bash
python -m vanguard.main
```

## Deploy (Netcup VPS)

Copy the repo to `/opt/vanguard`, install deps in a venv, then:

```bash
sudo cp deploy/vanguard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vanguard
```

## Status

Scaffolded per PRD v3.0. Not yet functional — see TODOs in
`vanguard/core/wallet_tracker.py` (mint resolution from account updates)
and `vanguard/main.py` (`insider_still_holding` balance check).
