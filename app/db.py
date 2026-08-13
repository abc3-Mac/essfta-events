"""SQLite layer for the ESSFTA Field Events calendar."""
import os
import sqlite3
import json
from datetime import datetime, timezone

DB_PATH = os.environ.get("EVENTS_DB", os.path.join(os.path.dirname(__file__), "..", "data", "events.db"))

REGIONS = ["East", "Mid East", "Mid West", "Rocky Mountain", "West"]

EVENT_TYPES = [
    "Field Trial", "Hunt Test", "Cocker Trial", "Fun Trial", "Water Test",
    "National", "Canadian Trial", "Gunning Seminar", "Judging Seminar", "Training Seminar",
]

REGION_COLORS = {  # canonical ESSFTA legend colors
    "East": "#2f5fa5",
    "Mid East": "#8f1d22",
    "Mid West": "#1f9d5b",
    "Rocky Mountain": "#b84390",
    "West": "#a3921e",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('governor','admin')),
    region TEXT,
    pw_hash TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    club TEXT NOT NULL DEFAULT '',
    region TEXT,
    event_type TEXT NOT NULL DEFAULT 'Field Trial',
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    city TEXT DEFAULT '',
    state TEXT DEFAULT '',
    venue TEXT DEFAULT '',
    stakes_open INTEGER DEFAULT 0,
    stakes_amateur INTEGER DEFAULT 0,
    stakes_puppy INTEGER DEFAULT 0,
    water_test INTEGER DEFAULT 0,
    cost TEXT DEFAULT '',
    entries_close TEXT DEFAULT '',
    judge1 TEXT DEFAULT '', judge2 TEXT DEFAULT '', judge3 TEXT DEFAULT '', judge4 TEXT DEFAULT '',
    apprentice_judges TEXT DEFAULT '',
    link_url TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'scheduled' CHECK(status IN ('scheduled','canceled','postponed','archived')),
    source TEXT DEFAULT 'manual',
    source_url TEXT DEFAULT '',
    created_by TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_by TEXT DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_date);
CREATE INDEX IF NOT EXISTS idx_events_region ON events(region);
CREATE TABLE IF NOT EXISTS event_history (
    id INTEGER PRIMARY KEY,
    event_id INTEGER NOT NULL,
    changed_by TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    action TEXT NOT NULL,
    snapshot_json TEXT NOT NULL
);
"""

EVENT_FIELDS = [
    "title", "club", "region", "event_type", "start_date", "end_date", "city", "state", "venue",
    "stakes_open", "stakes_amateur", "stakes_puppy", "water_test", "cost", "entries_close",
    "judge1", "judge2", "judge3", "judge4", "apprentice_judges", "link_url", "notes", "status",
]


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def connect():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init():
    con = connect()
    con.executescript(SCHEMA)
    cols = [r[1] for r in con.execute("PRAGMA table_info(users)")]
    if "active" not in cols:  # migration for DBs created before user management
        con.execute("ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
    con.commit()
    con.close()


def get_user(username, include_inactive=False):
    con = connect()
    q = "SELECT * FROM users WHERE username=?"
    if not include_inactive:
        q += " AND active=1"
    row = con.execute(q, (username,)).fetchone()
    con.close()
    return dict(row) if row else None


def list_users():
    con = connect()
    rows = [dict(r) for r in con.execute(
        "SELECT id, username, display_name, role, region, active, created_at FROM users "
        "ORDER BY role DESC, region, username")]
    con.close()
    return rows


def set_user_active(username, active):
    con = connect()
    con.execute("UPDATE users SET active=? WHERE username=?", (1 if active else 0, username))
    con.commit()
    con.close()


def create_user(username, display_name, role, region, pw_hash):
    con = connect()
    con.execute(
        "INSERT INTO users (username, display_name, role, region, pw_hash, created_at) VALUES (?,?,?,?,?,?)",
        (username, display_name, role, region, pw_hash, now()),
    )
    con.commit()
    con.close()


def set_password(username, pw_hash):
    con = connect()
    con.execute("UPDATE users SET pw_hash=? WHERE username=?", (pw_hash, username))
    con.commit()
    con.close()


def list_events(region=None, event_type=None, state=None, club=None, status=None,
                date_from=None, date_to=None, include_canceled=True):
    q = "SELECT * FROM events WHERE status != 'archived'"
    args = []
    if region:
        q += " AND region=?"; args.append(region)
    if event_type:
        q += " AND event_type=?"; args.append(event_type)
    if state:
        q += " AND state=? COLLATE NOCASE"; args.append(state)
    if club:
        q += " AND club LIKE ? COLLATE NOCASE"; args.append(f"%{club}%")
    if status:
        q += " AND status=?"; args.append(status)
    elif not include_canceled:
        q += " AND status = 'scheduled'"
    if date_from:
        q += " AND end_date >= ?"; args.append(date_from)
    if date_to:
        q += " AND start_date <= ?"; args.append(date_to)
    q += " ORDER BY start_date, region, title"
    con = connect()
    rows = [dict(r) for r in con.execute(q, args).fetchall()]
    con.close()
    return rows


def get_event(event_id):
    con = connect()
    row = con.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    con.close()
    return dict(row) if row else None


def _snapshot(con, event_id, username, action):
    row = con.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    con.execute(
        "INSERT INTO event_history (event_id, changed_by, changed_at, action, snapshot_json) VALUES (?,?,?,?,?)",
        (event_id, username, now(), action, json.dumps(dict(row) if row else {})),
    )


def create_event(data, username):
    con = connect()
    cols = [f for f in EVENT_FIELDS if f in data]
    vals = [data[f] for f in cols]
    cols += ["source", "created_by", "created_at", "updated_by", "updated_at"]
    vals += [data.get("source", "manual"), username, now(), username, now()]
    cur = con.execute(
        f"INSERT INTO events ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})", vals
    )
    event_id = cur.lastrowid
    _snapshot(con, event_id, username, "create")
    con.commit()
    con.close()
    return event_id


def update_event(event_id, data, username):
    con = connect()
    _snapshot(con, event_id, username, "before-update")
    cols = [f for f in EVENT_FIELDS if f in data]
    sets = ", ".join(f"{c}=?" for c in cols) + ", updated_by=?, updated_at=?"
    con.execute(
        f"UPDATE events SET {sets} WHERE id=?",
        [data[c] for c in cols] + [username, now(), event_id],
    )
    con.commit()
    con.close()


def set_status(event_id, status, username):
    con = connect()
    _snapshot(con, event_id, username, f"status:{status}")
    con.execute(
        "UPDATE events SET status=?, updated_by=?, updated_at=? WHERE id=?",
        (status, username, now(), event_id),
    )
    con.commit()
    con.close()


def distinct_states():
    con = connect()
    rows = [r[0] for r in con.execute(
        "SELECT DISTINCT state FROM events WHERE state != '' AND status != 'archived' ORDER BY state")]
    con.close()
    return rows
