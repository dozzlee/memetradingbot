import os
from dotenv import load_dotenv

load_dotenv()

HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")
HELIUS_RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

WALLET_POLL_INTERVAL_SECONDS = 10

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SOLANA_TRACKER_API_KEY = os.getenv("SOLANA_TRACKER_API_KEY", "")

TRACKED_WALLETS = [
    w.strip() for w in os.getenv("TRACKED_WALLETS", "").split(",") if w.strip()
]

# Stage 1 — mandatory safety window (seconds)
SAFETY_WINDOW_SECONDS = 20

# Stage 3 — hard abort if momentum conditions unmet within this window (seconds)
MOMENTUM_TIMEOUT_SECONDS = 180

# Rug-gate hard-block threshold: top-10 holder concentration (%)
TOP10_CONCENTRATION_LIMIT = 30

# PRD §7: only ~1% of pump.fun tokens graduate — a strong survival signal.
# Off by default: requiring it filters out most legitimate early entries,
# since the momentum gate is specifically about catching the second leg up
# *before* graduation. Flip on during calibration if false-positive rate
# on pre-graduation tokens turns out too high.
REQUIRE_PUMPFUN_GRADUATION = os.getenv("REQUIRE_PUMPFUN_GRADUATION", "false").lower() == "true"

# --- Execution wallet (custodial — see vanguard/wallet/) ---
WALLET_ENCRYPTION_KEY = os.getenv("WALLET_ENCRYPTION_KEY", "")

POSITION_SIZE_USD = float(os.getenv("POSITION_SIZE_USD", "5"))
MAX_CAPITAL_DEPLOYED_USD = float(os.getenv("MAX_CAPITAL_DEPLOYED_USD", "5"))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "50"))
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "20"))
SLIPPAGE_BPS = int(os.getenv("SLIPPAGE_BPS", "150"))

POSITION_POLL_INTERVAL_SECONDS = 10
