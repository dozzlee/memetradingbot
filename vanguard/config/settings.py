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
