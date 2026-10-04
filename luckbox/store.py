"""people.db: rebuilt from the sources on every ingest, so it never drifts from them."""
import os
import sqlite3

from . import config

SCHEMA = """
CREATE TABLE person (
  id INTEGER PRIMARY KEY, key TEXT UNIQUE, name TEXT,
  decision TEXT, label TEXT, note TEXT
);
CREATE TABLE handle (
  person_id INTEGER REFERENCES person(id), kind TEXT, value TEXT, UNIQUE(kind, value)
);
CREATE TABLE interaction (
  person_id INTEGER REFERENCES person(id), source TEXT,
  you_sent INTEGER, they_sent INTEGER, meetings INTEGER,
  first TEXT, last TEXT, subjects TEXT, context TEXT,
  PRIMARY KEY (person_id, source)
);
CREATE TABLE linkedin (
  id INTEGER PRIMARY KEY, person_id INTEGER REFERENCES person(id), key TEXT, name TEXT, email TEXT,
  company TEXT, position TEXT, connected_on TEXT, url TEXT, invite_note TEXT
);
"""


def db_path():
    return config.path("people.db")


def fresh():
    """A new empty database in place of the old one, readable only by the owner."""
    p = db_path()
    tmp = p + ".new"
    if os.path.exists(tmp):
        os.remove(tmp)
    os.close(os.open(tmp, os.O_CREAT | os.O_WRONLY, 0o600))
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)
    return con, tmp


def commit(con, tmp):
    con.commit()
    con.close()
    os.replace(tmp, db_path())


def connect():
    con = sqlite3.connect(db_path())
    con.row_factory = sqlite3.Row
    return con
