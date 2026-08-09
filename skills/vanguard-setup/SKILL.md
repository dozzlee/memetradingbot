---
name: vanguard-setup
description: Set up and operate the Vanguard Protocol Solana wallet-monitoring app, including secure API configuration, Telegram alerts, tracked-wallet onboarding, discovery scans, VPS deployment, and first-run verification.
---

# Vanguard Setup

Use this skill when the user asks to configure, install, onboard wallets, verify, or deploy the Vanguard Protocol project.

## Security rules

- Never write API keys, bot tokens, seed phrases, or private keys into this skill, source control, chat output, logs, or screenshots.
- Treat any credential pasted into chat as exposed. Tell the user to revoke and regenerate it before live use.
- Store credentials only in a local `.env` file with restrictive permissions, or in the VPS service's protected environment file.
- Vanguard must never hold a private key, sign a transaction, or execute a trade.

## Setup workflow

1. Confirm the repository and inspect `requirements.txt`, `README.md`, `vanguard/config/settings.py`, `deploy/vanguard.service`, and `WEB_APP_GUIDE.md`.
2. Create or activate the virtual environment.
3. Install dependencies.
4. Create `.env` locally without printing its contents:

   ```dotenv
   HELIUS_API_KEY=<new-helius-key>
   SOLANA_TRACKER_API_KEY=<optional-new-solana-tracker-key>
   TELEGRAM_BOT_TOKEN=<new-telegram-bot-token>
   TELEGRAM_CHAT_ID=<private-chat-or-channel-id>
   TRACKED_WALLETS=3XcHbc5Z7GfM3nXkP7NE8GT7ZawVsekxEfmPCofD1kcc
   REQUIRE_PUMPFUN_GRADUATION=false
   ```

   The example wallet is a candidate to review, not automatically trusted.

5. Restrict permissions:

   ```bash
   chmod 600 .env
   ```

6. Validate the setup without exposing secrets:
   - Check required variables are non-empty using a script or shell test that prints only variable names and `set`/`missing` status.
   - Call Telegram `getMe` and report only the bot username and success/failure.
   - Send a test message only after the user confirms the chat ID and asks for a test alert.
   - Start the app and verify `/api/status` returns successfully.
7. Open the dashboard at `http://127.0.0.1:8000`.
8. Review the supplied wallet in Solscan and run its backtest before starting monitoring.
9. Run **Discover Wallets**, inspect full addresses, backtest candidates, and only then track a wallet.
10. Keep monitoring stopped until the wallet list, Telegram destination, and risk settings are verified.

## Finding the Telegram chat ID

Do not guess the chat ID. Add the bot to the intended private chat/channel, send a message there, then query Telegram `getUpdates` with the bot token. Extract the relevant `chat.id` locally and never print the token or full update payload. For a channel, the bot must have permission to post.

## First-run verification

Verify these paths in order:

1. Dashboard loads.
2. `/api/status` shows the expected wallet and configuration.
3. Token Inspector can analyze a known mint.
4. Wallet Discovery returns candidate records or a clear no-results response.
5. A candidate can be copied, opened in Solscan, backtested, and added to tracking.
6. Start/stop changes the monitor state.
7. Decision events and manual trades persist after restart.

Do not call the setup complete until these checks pass or the exact failing check is reported.

## VPS deployment

On a fresh Ubuntu VPS, first verify SSH key access in a second session. Then run:

```bash
sudo bash deploy/harden.sh
```

Copy the project to `/opt/vanguard`, create `/opt/vanguard/.env` with mode `600`, install the virtual environment, then install and enable:

```bash
sudo cp deploy/vanguard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vanguard
sudo journalctl -u vanguard -f
```

Keep the dashboard on `127.0.0.1`; access it through an SSH tunnel unless a separately authenticated reverse proxy is configured.

## Operational workflow

- Review a wallet before tracking it.
- Use fixed `$5` manual trades during calibration.
- Configure stop-loss and take-profit rules in the external execution bot.
- Treat alerts as review prompts, not automatic buys.
- Record entry, exit, fees, and outcome in the Trade Ledger.
- Do not scale until the ledger shows positive expectancy after fees and slippage.
- Remember that sell-route/honeypot simulation is not yet implemented; the rug gate is necessary but not sufficient.

## Useful project references

- `WEB_APP_GUIDE.md` — operator instructions.
- `scripts/find_cluster.py` — developer-specific cluster overlap analysis.
- `vanguard/discovery.py` — broader early-wallet candidate discovery.
- `vanguard/backtest.py` — wallet and token analysis.
- `deploy/harden.sh` — VPS hardening.
