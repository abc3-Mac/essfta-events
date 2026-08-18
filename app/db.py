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
    stakes_cocker INTEGER DEFAULT 0,
    water_test INTEGER DEFAULT 0,
    cost TEXT DEFAULT '',
    entries_close TEXT DEFAULT '',
    judge1 TEXT DEFAULT '', judge2 TEXT DEFAULT '', judge3 TEXT DEFAULT '', judge4 TEXT DEFAULT '',
    apprentice_judges TEXT DEFAULT '',
    link_url TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'scheduled' CHECK(status IN ('scheduled','canceled','postponed','archived')),
    hidden INTEGER NOT NULL DEFAULT 0,
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
    snapshot_json TEXT NOT NULL,
    batch_id TEXT
);
CREATE TABLE IF NOT EXISTS login_events (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    event TEXT NOT NULL CHECK(event IN ('login_ok','login_failed','rate_limited','logout')),
    at TEXT NOT NULL,
    ip TEXT DEFAULT '',
    user_agent TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_login_events_at ON login_events(at);
CREATE INDEX IF NOT EXISTS idx_login_events_user ON login_events(username);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_by TEXT DEFAULT '',
    updated_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS batches (
    id TEXT PRIMARY KEY,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    action TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    event_count INTEGER NOT NULL DEFAULT 0,
    undone_at TEXT
);
"""

EVENT_FIELDS = [
    "title", "club", "region", "event_type", "start_date", "end_date", "city", "state", "venue",
    "stakes_open", "stakes_amateur", "stakes_puppy", "stakes_cocker", "water_test", "cost", "entries_close",
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
    ecols = [r[1] for r in con.execute("PRAGMA table_info(events)")]
    if "stakes_cocker" not in ecols:  # migration: cocker stakes run alongside springer trials
        con.execute("ALTER TABLE events ADD COLUMN stakes_cocker INTEGER DEFAULT 0")
    if "hidden" not in ecols:  # migration: Hide (off public views, kept in place) is now distinct from Remove
        con.execute("ALTER TABLE events ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")
    hcols = [r[1] for r in con.execute("PRAGMA table_info(event_history)")]
    if "batch_id" not in hcols:  # migration: bulk operations group their changes for wholesale undo
        con.execute("ALTER TABLE event_history ADD COLUMN batch_id TEXT")
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
                date_from=None, date_to=None, include_canceled=True, include_hidden=False):
    q = "SELECT * FROM events WHERE 1=1"
    args = []
    if not status:  # archived events only appear when asked for explicitly
        q += " AND status != 'archived'"
    if not include_hidden:  # hidden events never reach public views
        q += " AND hidden=0"
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


def _snapshot(con, event_id, username, action, batch_id=None):
    row = con.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    con.execute(
        "INSERT INTO event_history (event_id, changed_by, changed_at, action, snapshot_json, batch_id) "
        "VALUES (?,?,?,?,?,?)",
        (event_id, username, now(), action, json.dumps(dict(row) if row else {}), batch_id),
    )


def create_event(data, username, batch_id=None):
    con = connect()
    cols = [f for f in EVENT_FIELDS if f in data]
    vals = [data[f] for f in cols]
    cols += ["source", "created_by", "created_at", "updated_by", "updated_at"]
    vals += [data.get("source", "manual"), username, now(), username, now()]
    cur = con.execute(
        f"INSERT INTO events ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})", vals
    )
    event_id = cur.lastrowid
    _snapshot(con, event_id, username, "create", batch_id)
    con.commit()
    con.close()
    return event_id


def update_event(event_id, data, username, batch_id=None, action="before-update"):
    con = connect()
    _snapshot(con, event_id, username, action, batch_id)
    cols = [f for f in EVENT_FIELDS if f in data]
    sets = ", ".join(f"{c}=?" for c in cols) + ", updated_by=?, updated_at=?"
    con.execute(
        f"UPDATE events SET {sets} WHERE id=?",
        [data[c] for c in cols] + [username, now(), event_id],
    )
    con.commit()
    con.close()


def restore_snapshot(event_id, snap, username, batch_id=None):
    """Put an event back to a prior event_history snapshot — fields, status, and
    hidden flag alike. The workhorse of batch undo."""
    con = connect()
    _snapshot(con, event_id, username, "undo-restore", batch_id)
    cols = [f for f in EVENT_FIELDS if f in snap]
    sets = ", ".join(f"{c}=?" for c in cols) + ", hidden=?, updated_by=?, updated_at=?"
    con.execute(
        f"UPDATE events SET {sets} WHERE id=?",
        [snap[c] for c in cols] + [snap.get("hidden", 0), username, now(), event_id],
    )
    con.commit()
    con.close()


def set_status(event_id, status, username, batch_id=None):
    con = connect()
    _snapshot(con, event_id, username, f"status:{status}", batch_id)
    con.execute(
        "UPDATE events SET status=?, updated_by=?, updated_at=? WHERE id=?",
        (status, username, now(), event_id),
    )
    con.commit()
    con.close()


def set_hidden(event_id, hidden, username, batch_id=None):
    """Hide keeps the event exactly as it is (status, place on the dashboard) but
    drops it from every public view. Distinct from Remove (status=archived)."""
    con = connect()
    _snapshot(con, event_id, username, f"hidden:{1 if hidden else 0}", batch_id)
    con.execute(
        "UPDATE events SET hidden=?, updated_by=?, updated_at=? WHERE id=?",
        (1 if hidden else 0, username, now(), event_id),
    )
    con.commit()
    con.close()


# ---------- site settings ----------

def get_setting(key, default=""):
    con = connect()
    row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    con.close()
    return row["value"] if row else default


def set_setting(key, value, username):
    con = connect()
    con.execute(
        "INSERT INTO settings (key, value, updated_by, updated_at) VALUES (?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_by=excluded.updated_by, "
        "updated_at=excluded.updated_at",
        (key, value, username, now()),
    )
    con.commit()
    con.close()


# ---------- login audit ----------

def log_login(username, event, ip="", user_agent=""):
    """Never store the submitted password or session token — only who/what/when/where."""
    con = connect()
    con.execute(
        "INSERT INTO login_events (username, event, at, ip, user_agent) VALUES (?,?,?,?,?)",
        (username[:80], event, now(), ip[:60], user_agent[:150]),
    )
    con.commit()
    con.close()


def list_login_events(username=None, date_from=None, date_to=None, limit=500):
    q = "SELECT * FROM login_events WHERE 1=1"
    args = []
    if username:
        q += " AND username=?"; args.append(username)
    if date_from:
        q += " AND at >= ?"; args.append(date_from)
    if date_to:
        q += " AND at <= ?"; args.append(date_to + " 23:59:59")
    q += " ORDER BY at DESC, id DESC LIMIT ?"
    args.append(limit)
    con = connect()
    rows = [dict(r) for r in con.execute(q, args).fetchall()]
    con.close()
    return rows


def last_seen_map():
    """username -> most recent successful login (UTC), for the /users page."""
    con = connect()
    rows = con.execute(
        "SELECT username, MAX(at) AS at FROM login_events WHERE event='login_ok' GROUP BY username")
    out = {r["username"]: r["at"] for r in rows}
    con.close()
    return out


def recent_event_changes(limit=100):
    """Global who-changed-what feed for the admin audit page."""
    con = connect()
    rows = [dict(r) for r in con.execute(
        "SELECT h.event_id, h.changed_by, h.changed_at, h.action, h.batch_id, "
        "       COALESCE(e.club, '') AS club, COALESCE(e.title, '') AS title, "
        "       COALESCE(e.start_date, '') AS start_date, COALESCE(e.region, '') AS region "
        "FROM event_history h LEFT JOIN events e ON e.id = h.event_id "
        "ORDER BY h.changed_at DESC, h.id DESC LIMIT ?", (limit,))]
    con.close()
    return rows


def bulk_select(date_from, date_to, region="ALL", statuses=None, hidden=None):
    """Events starting in [date_from, date_to]. region: 'ALL', 'NONE' (no region), or a
    region name. hidden: None = either, 0/1 to filter."""
    q = "SELECT * FROM events WHERE start_date >= ? AND start_date <= ?"
    args = [date_from, date_to]
    if region == "NONE":
        q += " AND region IS NULL"
    elif region != "ALL":
        q += " AND region=?"; args.append(region)
    if statuses:
        q += f" AND status IN ({','.join('?' * len(statuses))})"; args.extend(statuses)
    if hidden is not None:
        q += " AND hidden=?"; args.append(hidden)
    q += " ORDER BY start_date, region, title"
    con = connect()
    rows = [dict(r) for r in con.execute(q, args).fetchall()]
    con.close()
    return rows


# ---------- bulk operation batches ----------

def create_batch(batch_id, username, action, description, event_count):
    con = connect()
    con.execute(
        "INSERT INTO batches (id, created_by, created_at, action, description, event_count) VALUES (?,?,?,?,?,?)",
        (batch_id, username, now(), action, description, event_count),
    )
    con.commit()
    con.close()


def get_batch(batch_id):
    con = connect()
    row = con.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
    con.close()
    return dict(row) if row else None


def list_batches(created_by=None, limit=20):
    q = "SELECT * FROM batches"
    args = []
    if created_by:
        q += " WHERE created_by=?"; args.append(created_by)
    q += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    con = connect()
    rows = [dict(r) for r in con.execute(q, args).fetchall()]
    con.close()
    return rows


def batch_history(batch_id):
    """The per-event snapshots a bulk operation wrote — the raw material for undo."""
    con = connect()
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM event_history WHERE batch_id=? ORDER BY id", (batch_id,))]
    con.close()
    return rows


def mark_batch_undone(batch_id):
    con = connect()
    con.execute("UPDATE batches SET undone_at=? WHERE id=?", (now(), batch_id))
    con.commit()
    con.close()


def find_near_duplicate(club, start_iso, days=30):
    """An unarchived event for the same club within ±days of the date — roll-forward
    skips these so a club already entered by hand isn't cloned on top of."""
    if not club:
        return None
    con = connect()
    row = con.execute(
        "SELECT id, start_date FROM events WHERE club=? COLLATE NOCASE AND status != 'archived' "
        "AND start_date BETWEEN date(?, ?) AND date(?, ?) LIMIT 1",
        (club, start_iso, f"-{days} days", start_iso, f"+{days} days")).fetchone()
    con.close()
    return dict(row) if row else None


def distinct_event_years():
    con = connect()
    rows = [r[0] for r in con.execute(
        "SELECT DISTINCT substr(start_date, 1, 4) FROM events WHERE status != 'archived' ORDER BY 1")]
    con.close()
    return [int(y) for y in rows if y and y.isdigit()]


def distinct_states():
    con = connect()
    rows = [r[0] for r in con.execute(
        "SELECT DISTINCT state FROM events WHERE state != '' AND status != 'archived' ORDER BY state")]
    con.close()
    return rows
