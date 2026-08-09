# Vanguard Protocol Web App Guide

Vanguard is an alerting and analysis tool. It never holds a private key, signs a transaction, or executes a trade. Any trade is performed manually in your third-party Telegram trading bot.

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

Do not put private keys in `.env` or on the VPS.

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
5. Sends only cleared candidates to Telegram.

Treat a Telegram alert as a prompt for human review—not an automatic buy signal. Open the token in Solscan and your execution bot, check slippage and liquidity, then decide whether to trade.

## 6. Inspect a token manually

Use **Token Inspector** before acting on a token:

1. Paste the token mint address.
2. Click **Analyze**.
3. Review the Rug Gate verdict and reasons.
4. Review momentum, liquidity, buy/sell activity, and graduation status.

The inspector is useful for analysis but does not simulate a real sell route. The honeypot/sell-route check remains a known safety gap.

## 7. Record trades

The **Trade Ledger** is manual because Vanguard does not execute trades.

To record an entry, enter:

- token mint;
- source wallet, if relevant;
- actual entry price in USD;
- position size, normally `$5` during calibration.

After selling, enter the exit price and fees, then click **Close**. The app calculates realized P&L and marks the trade as a win, loss, or breakeven.

Use this ledger to calibrate thresholds. Do not increase position size until the ledger shows sustained positive expectancy after fees and slippage.

## 8. Read the dashboard sections

- **Status** — whether monitoring is running and the active safety settings.
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
- Keep the execution wallet separate from personal funds.
- Configure stop-loss and take-profit rules in the external trading bot.
- Start with the PRD’s fixed `$5` trade size.
- Check the token manually after every alert.
- Record every entry, exit, fee, and outcome.
- Remember that sell-route simulation is not yet implemented and memecoin trading can lose the full position.
