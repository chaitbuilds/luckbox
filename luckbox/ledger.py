"""ledger.db: everything the radars have seen, what the judge said, what was suggested, and how
you marked it. Unlike people.db it is never rebuilt; it is the memory that makes luckbox improve."""
import os
import re
import sqlite3

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS item (
  id TEXT PRIMARY KEY, radar TEXT, source TEXT, kind TEXT, title TEXT, url TEXT,
  authors TEXT, published TEXT, snippet TEXT, fetched_at TEXT,
  status TEXT DEFAULT 'new'            -- new | judged | error
);
CREATE TABLE IF NOT EXISTS judgment (
  item_id TEXT PRIMARY KEY REFERENCES item(id), pass INTEGER, score REAL,
  move TEXT, why TEXT, person TEXT, judged_at TEXT, rubric TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS suggestion (
  id INTEGER PRIMARY KEY, item_id TEXT REFERENCES item(id), day TEXT, rank INTEGER,
  move TEXT, why TEXT, url TEXT, mark TEXT, note TEXT, marked_at TEXT
);
CREATE TABLE IF NOT EXISTS run (
  id INTEGER PRIMARY KEY, started TEXT, step TEXT, detail TEXT, cost_usd REAL
);
"""


def connect():
    p = config.path("ledger.db")
    if not os.path.exists(p):
        os.close(os.open(p, os.O_CREAT | os.O_WRONLY, 0o600))
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    for table, column in (("item", "title_key"), ("judgment", "headline"), ("suggestion", "headline")):
        try:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
        except sqlite3.OperationalError:
            pass
    return con


def title_key(title):
    return re.sub(r"[^a-z0-9]", "", (title or "").lower())[:120]


def prune(con, keep_days=60):
    """Bound the ledger: drop items older than keep_days that were never suggested (their
    judgments too). Suggestions and your marks are kept forever; they are what luckbox learns from."""
    cutoff = f"-{int(keep_days)} days"
    old = "SELECT id FROM item WHERE fetched_at < datetime('now', ?) AND id NOT IN (SELECT item_id FROM suggestion)"
    con.execute(f"DELETE FROM judgment WHERE item_id IN ({old})", (cutoff,))
    n = con.execute(f"DELETE FROM item WHERE id IN ({old})", (cutoff,)).rowcount
    con.commit()
    con.execute("VACUUM")
    return n
