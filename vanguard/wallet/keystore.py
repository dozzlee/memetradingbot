"""The bot's own Solana execution wallet — generation, encrypted storage,
and balance reads.

The private key never lives in the database or in plaintext on disk: it's
encrypted at rest with a Fernet key (`WALLET_ENCRYPTION_KEY`, .env-only,
never committed) and only decrypted in memory for the moment it's needed
to sign a transaction (see vanguard/wallet/jupiter.py). The public address
is stored in the DB (`bot_wallet` table) since it isn't sensitive.

This module intentionally never logs, returns, or prints the secret key
bytes or seed — every function that needs the live keypair returns it to
the caller directly, not through logging/state that could leak it.
"""
import os
import stat
from pathlib import Path

import requests
from cryptography.fernet import Fernet, InvalidToken
from solders.keypair import Keypair

from vanguard import db
from vanguard.config import settings

KEY_PATH = Path(__file__).parent.parent.parent / "vanguard_wallet.enc"


class WalletError(RuntimeError):
    pass


def _fernet() -> Fernet:
    if not settings.WALLET_ENCRYPTION_KEY:
        raise WalletError(
            "WALLET_ENCRYPTION_KEY is not set in .env — generate one with "
            "`python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"`, back it up somewhere "
            "other than this machine, then add it to .env."
        )
    try:
        return Fernet(settings.WALLET_ENCRYPTION_KEY.encode())
    except (ValueError, TypeError) as e:
        raise WalletError(f"WALLET_ENCRYPTION_KEY is not a valid Fernet key: {e}") from e


def exists() -> bool:
    return KEY_PATH.exists() and db.get_bot_wallet() is not None


def get_address() -> str | None:
    row = db.get_bot_wallet()
    return row["address"] if row else None


def create_wallet() -> str:
    """Generates a new keypair and persists it encrypted. Refuses to
    overwrite an existing wallet — recovering/rotating funds out of the old
    one is a manual, deliberate action, not something a re-run should do
    silently."""
    if exists():
        raise WalletError(
            f"a wallet already exists ({get_address()}). Refusing to overwrite it — "
            "move its funds out first if you want to replace it."
        )

    fernet = _fernet()
    keypair = Keypair()
    encrypted = fernet.encrypt(bytes(keypair))

    KEY_PATH.write_bytes(encrypted)
    os.chmod(KEY_PATH, stat.S_IRUSR | stat.S_IWUSR)  # 600 — owner read/write only

    address = str(keypair.pubkey())
    db.set_bot_wallet(address)
    return address


def load_keypair() -> Keypair:
    if not KEY_PATH.exists():
        raise WalletError("no wallet found — create one first (dashboard 'Create Wallet' or POST /api/wallet/init).")
    fernet = _fernet()
    encrypted = KEY_PATH.read_bytes()
    try:
        secret_bytes = fernet.decrypt(encrypted)
    except InvalidToken as e:
        raise WalletError(
            "failed to decrypt vanguard_wallet.enc — WALLET_ENCRYPTION_KEY doesn't match "
            "the key this wallet was created with."
        ) from e
    return Keypair.from_bytes(secret_bytes)


def get_sol_balance(address: str) -> float:
    resp = requests.post(
        settings.HELIUS_RPC_URL,
        json={"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [address]},
        timeout=10,
    )
    resp.raise_for_status()
    lamports = resp.json().get("result", {}).get("value", 0)
    return lamports / 1_000_000_000


def get_token_balance(address: str, mint: str) -> tuple[float, int]:
    """Returns (ui_amount, decimals) for a given SPL token held by `address`.
    (0, 0) if the token account doesn't exist / has no balance."""
    resp = requests.post(
        settings.HELIUS_RPC_URL,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [address, {"mint": mint}, {"encoding": "jsonParsed"}],
        },
        timeout=10,
    )
    resp.raise_for_status()
    accounts = resp.json().get("result", {}).get("value", [])
    for acct in accounts:
        info = acct["account"]["data"]["parsed"]["info"]["tokenAmount"]
        amount = info["uiAmount"]
        if amount and amount > 0:
            return float(amount), int(info["decimals"])
    return 0.0, 0
