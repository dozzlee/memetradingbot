# Vanguard Protocol Web App Guide

Vanguard watches insider wallets and runs the safety/momentum gates as before, but it can now also
hold a Solana wallet of its own and trade with it: a Telegram Buy/Skip button on each cleared alert
triggers a real swap, and an open position exits automatically at a fixed take-profit/stop-loss.
This is a **custodial** feature — the bot generates and stores a real private key and signs real
transactions with it. Read §2a below before funding anything.

## 1. Start the app

From the repository directory:

```bash
source .venv/bin/activate
python -m vanguard.main
```

Open `http://127.0.0.1:8000` in your browser.

On a VPS, keep the dashboard bound to localhost and use an SSH tunnel:

```bash
ssh -L 8000:localhost:8000 vanguard@YOUR_SERVER_IP
```

Then open `http://127.0.0.1:8000` locally.

## 2. Configure environment variables

Create `.env` from the project template and set:

- `HELIUS_API_KEY` — required for wallet monitoring and wallet discovery.
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` — required for filtered alerts.
- `TRACKED_WALLETS` — optional comma-separated starting wallets.
- `SOLANA_TRACKER_API_KEY` — optional risk cross-check.
- `REQUIRE_PUMPFUN_GRADUATION=true` — optional; filters out tokens that have not graduated from pump.fun.
- `WALLET_ENCRYPTION_KEY` — required before creating an execution wallet (§2a).
- `POSITION_SIZE_USD`, `MAX_CAPITAL_DEPLOYED_USD`, `TAKE_PROFIT_PCT`, `STOP_LOSS_PCT`, `SLIPPAGE_BPS` — auto-trade sizing and exit rules; defaults are `$5` / `$5` / `+50%` / `-20%` / `1.5%`.

## 2a. Set up the execution wallet (custodial — reads this before funding)

The bot's private key is encrypted at rest with `WALLET_ENCRYPTION_KEY` and decrypted in memory only
at the moment it signs a swap. That encryption key is the single point of failure for the wallet's
funds — **generate it and back it up before creating the wallet, on the machine that will actually
keep running (your VPS), not a throwaway session:**

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Put the output in `.env` as `WALLET_ENCRYPTION_KEY=...`, `chmod 600 .env`, and copy the key itself
somewhere durable and offline (a password manager, not this repo, not a chat log). If it's lost, the
wallet's funds are unrecoverable — there is no reset-password flow for a Solana keypair.

Then, from the dashboard's **Execution Wallet** card, click **Create Wallet**. This generates a new
Solana keypair, encrypts it into `vanguard_wallet.enc` (git-ignored, `chmod 600`), and shows the
deposit address. Fund it with only what you're willing to trade with — each auto-trade risks a fixed
`POSITION_SIZE_USD`, and `MAX_CAPITAL_DEPLOYED_USD` caps how much can be in flight across open
positions at once. Keep a little extra SOL beyond that for network/priority fees.

Do not put the private key anywhere else — not in `.env`, not in chat, not in a screenshot.

## 3. Discover candidate wallets

Use **Discover Wallets** to scan currently visible Solana tokens and identify wallets that appeared among the early buyers of multiple tokens.

1. Set a minimum market-cap floor. Start with `$500,000`.
2. Click **Scan**.
3. Review the complete wallet addresses returned for each candidate.
4. Use **Solscan** to inspect the address.
5. Use **backtest** to review its recent historical buys and current returns.
6. Click **track** only after manual review.

The scan is a candidate generator, not proof that a wallet belongs to an insider cluster. For a developer-specific cluster, use `scripts/find_cluster.py` with three or more known launches from the same developer.

## 4. Add and monitor wallets

In **Tracked Wallets**:

- Paste a Solana wallet address and click **Add**.
- Use **backtest** to inspect its track record.
- Use **remove** to stop tracking it.
- Click **Start** only after the wallet list is correct.

The monitor listens for wallet activity through Helius WebSockets. If the socket drops, it falls back to REST polling. Click **Stop** when you want to pause monitoring.

## 5. Understand a live alert

For each tracked-wallet buy, Vanguard:

1. Waits through the safety window.
2. Runs the RugCheck safety gate.
3. Watches price behavior, buy/sell activity, liquidity, pump.fun graduation status, and whether the source wallet still holds.
4. Aborts after the configured momentum timeout if conditions do not qualify.
5. Sends only cleared candidates to Telegram, with **Buy** and **Skip** buttons.

Nothing trades until you tap **Buy**. Tapping it fires a real swap for `POSITION_SIZE_USD` — review
the token (Solscan, liquidity, the reasons listed) before tapping, the same way you would before any
manual trade. If a position is already open, Buy is refused (only one open position at a time under
the current `MAX_CAPITAL_DEPLOYED_USD` == `POSITION_SIZE_USD` config) — tap Skip or wait for the open
position to exit. Once bought, the exit is automatic: no button, no manual step — it sells itself at
`+TAKE_PROFIT_PCT%` or `-STOP_LOSS_PCT%` and posts the result back to the same chat.

## 6. Inspect a token manually

Use **Token Inspector** before acting on a token:

1. Paste the token mint address.
2. Click **Analyze**.
3. Review the Rug Gate verdict and reasons.
4. Review momentum, liquidity, buy/sell activity, and graduation status.

The inspector is useful for analysis but does not simulate a real sell route. The honeypot/sell-route check remains a known safety gap.

## 7. Record trades

Auto-trades (bought via the Telegram Buy button) write to the **Trade Ledger** automatically, with the
actual on-chain fill price and transaction signatures — nothing to enter by hand. The manual-entry
form is still there for trades you make outside the bot (e.g. in a separate execution bot), or from
before this feature existed.

To record a manual entry, enter:

- token mint;
- source wallet, if relevant;
- actual entry price in USD;
- position size, normally `$5` during calibration.

After selling, enter the exit price and fees, then click **Close**. The app calculates realized P&L and marks the trade as a win, loss, or breakeven.

Use this ledger to calibrate thresholds. Do not increase position size until the ledger shows sustained positive expectancy after fees and slippage.

## 8. Read the dashboard sections

- **Status** — whether monitoring is running and the active safety settings.
- **Execution Wallet** — deposit address, SOL/USD balance, open position, auto-trade config.
- **Tracked Wallets** — wallets currently monitored.
- **Discover Wallets** — candidate early-money addresses.
- **Token Inspector** — on-demand safety and momentum analysis.
- **Cleared Alerts** — candidates that passed the live gates.
- **Decision Log** — buy detected, rejected, aborted, cleared, and error events.
- **Trade Ledger** — manual execution and outcome history.

## 9. VPS operation

On a fresh Ubuntu VPS, run the hardening script as root after verifying key-based SSH access:

```bash
sudo bash deploy/harden.sh
```

Install and enable the service:

```bash
sudo cp deploy/vanguard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vanguard
```

Check logs with:

```bash
sudo journalctl -u vanguard -f
```

## 10. Safety checklist before live use

- Confirm the tracked wallets are genuinely reviewed clusters.
- Back up `WALLET_ENCRYPTION_KEY` somewhere durable and offline before funding the wallet — losing it
  loses the funds, permanently.
- Fund only what you're willing to lose entirely; keep this wallet separate from personal funds.
- Confirm `POSITION_SIZE_USD` / `MAX_CAPITAL_DEPLOYED_USD` / `TAKE_PROFIT_PCT` / `STOP_LOSS_PCT` in
  `.env` match what you actually intend before the first live Buy tap.
- Review the token (Solscan, the alert's listed reasons) before tapping Buy — the button fires a real
  swap immediately, there's no second confirmation.
- Remember that sell-route simulation is not implemented and memecoin trading can lose the full
  position even with stop-loss configured — a token can go effectively illiquid faster than the
  position-monitor's poll interval can react.
