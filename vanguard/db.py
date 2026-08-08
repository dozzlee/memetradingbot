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
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
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


# --- trade ledger (manual — the bot never executes, so entries/exits are
# logged by hand from the dashboard after you act on an alert) ---

def open_trade(mint: str, wallet: str, entry_price_usd: float, size_usd: float, notes: str = "") -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO trades (mint, wallet, opened_at, entry_price_usd, size_usd, notes) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (mint, wallet, time.time(), entry_price_usd, size_usd, notes),
    )
    conn.commit()
    trade_id = cur.lastrowid
    conn.close()
    return trade_id


def close_trade(trade_id: int, exit_price_usd: float, fees_usd: float = 0.0):
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
        "UPDATE trades SET closed_at = ?, exit_price_usd = ?, fees_usd = ?, pnl_usd = ?, outcome = ? "
        "WHERE id = ?",
        (time.time(), exit_price_usd, fees_usd, pnl, outcome, trade_id),
    )
    conn.commit()
    conn.close()
    return pnl


def list_trades(limit: int = 200) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
