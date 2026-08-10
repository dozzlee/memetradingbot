"""SQLite persistence — wallets, decision events, alerts, and a manual
trade ledger. Single file, no server; survives restarts (PRD gap: state
was previously in-memory only)."""
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "vanguard.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS wallets (
    address TEXT PRIMARY KEY,
    label TEXT,
    added_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    wallet TEXT,
    mint TEXT,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    mint TEXT NOT NULL,
    wallet TEXT,
    risk_score TEXT,
    buy_sell_ratio TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mint TEXT NOT NULL,
    wallet TEXT,
    opened_at REAL NOT NULL,
    entry_price_usd REAL,
    size_usd REAL,
    closed_at REAL,
    exit_price_usd REAL,
    fees_usd REAL,
    pnl_usd REAL,
    outcome TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS bot_wallet (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    address TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""

# Columns added after the original trades table shipped — SQLite has no
# "ADD COLUMN IF NOT EXISTS", so probe-and-add instead. Needed for auto-trades
# (execute_buy/execute_sell) to record the actual on-chain fill and tx sigs
# alongside the pre-existing manual-entry columns above.
TRADES_MIGRATIONS = [
    ("token_amount", "REAL"),
    ("decimals", "INTEGER"),
    ("entry_tx_sig", "TEXT"),
    ("exit_tx_sig", "TEXT"),
    ("auto", "INTEGER DEFAULT 0"),
]


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(trades)")}
    for name, coltype in TRADES_MIGRATIONS:
        if name not in existing:
            conn.execute(f"ALTER TABLE trades ADD COLUMN {name} {coltype}")
    conn.commit()
    conn.close()


# --- wallets ---

def list_wallets() -> list[str]:
    conn = get_conn()
    rows = conn.execute("SELECT address FROM wallets ORDER BY added_at").fetchall()
    conn.close()
    return [r["address"] for r in rows]


def add_wallet(address: str, label: str = ""):
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO wallets (address, label, added_at) VALUES (?, ?, ?)",
        (address, label, time.time()),
    )
    conn.commit()
    conn.close()


def remove_wallet(address: str):
    conn = get_conn()
    conn.execute("DELETE FROM wallets WHERE address = ?", (address,))
    conn.commit()
    conn.close()


# --- events / alerts ---

def log_event(kind: str, wallet: str, mint: str, detail: str = ""):
    conn = get_conn()
    conn.execute(
        "INSERT INTO events (ts, kind, wallet, mint, detail) VALUES (?, ?, ?, ?, ?)",
        (time.time(), kind, wallet, mint, detail),
    )
    conn.commit()
    conn.close()


def list_events(limit: int = 200) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def log_alert(mint: str, wallet: str, risk_score, buy_sell_ratio: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO alerts (ts, mint, wallet, risk_score, buy_sell_ratio) VALUES (?, ?, ?, ?, ?)",
        (time.time(), mint, wallet, str(risk_score), buy_sell_ratio),
    )
    conn.commit()
    conn.close()


def list_alerts(limit: int = 100) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- trade ledger. Manual trades are logged by hand from the dashboard;
# auto trades (auto=1) are opened/closed by vanguard/execution/trader.py
# against the bot's own wallet, using the actual on-chain fill instead of
# a hand-entered price. ---

def open_trade(
    mint: str,
    wallet: str,
    entry_price_usd: float,
    size_usd: float,
    notes: str = "",
    token_amount: float | None = None,
    decimals: int | None = None,
    entry_tx_sig: str | None = None,
    auto: bool = False,
) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO trades (mint, wallet, opened_at, entry_price_usd, size_usd, notes, "
        "token_amount, decimals, entry_tx_sig, auto) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (mint, wallet, time.time(), entry_price_usd, size_usd, notes,
         token_amount, decimals, entry_tx_sig, int(auto)),
    )
    conn.commit()
    trade_id = cur.lastrowid
    conn.close()
    return trade_id


def close_trade(trade_id: int, exit_price_usd: float, fees_usd: float = 0.0, exit_tx_sig: str | None = None):
    conn = get_conn()
    row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    if row is None:
        conn.close()
        raise ValueError(f"no trade {trade_id}")

    entry_price = row["entry_price_usd"] or 0
    size_usd = row["size_usd"] or 0
    tokens = (size_usd / entry_price) if entry_price else 0
    gross = tokens * exit_price_usd
    pnl = gross - size_usd - fees_usd
    outcome = "win" if pnl > 0 else ("loss" if pnl < 0 else "breakeven")

    conn.execute(
        "UPDATE trades SET closed_at = ?, exit_price_usd = ?, fees_usd = ?, pnl_usd = ?, outcome = ?, "
        "exit_tx_sig = ? WHERE id = ?",
        (time.time(), exit_price_usd, fees_usd, pnl, outcome, exit_tx_sig, trade_id),
    )
    conn.commit()
    conn.close()
    return pnl


def open_trades() -> list[dict]:
    """Trades with no closed_at yet — used at startup to resume position monitors."""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM trades WHERE closed_at IS NULL AND auto = 1").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- bot execution wallet (singleton row; the encrypted key itself lives
# outside the DB, see vanguard/wallet/keystore.py) ---

def get_bot_wallet() -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM bot_wallet WHERE id = 1").fetchone()
    conn.close()
    return dict(row) if row else None


def set_bot_wallet(address: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO bot_wallet (id, address, created_at) VALUES (1, ?, ?) "
        "ON CONFLICT(id) DO NOTHING",
        (address, time.time()),
    )
    conn.commit()
    conn.close()


def list_trades(limit: int = 200) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
