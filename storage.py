"""SQLite persistence, session ownership, retention, and transactional run budgets."""
import csv
from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path
import secrets
import sqlite3
import time

SESSION_SECONDS = 7 * 86400


class CapacityError(Exception):
    pass


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (owner TEXT PRIMARY KEY, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, created REAL NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS runs_owner ON runs(owner, created);
                CREATE TABLE IF NOT EXISTS starts (owner TEXT, ip TEXT, live INTEGER, created REAL);
                CREATE INDEX IF NOT EXISTS starts_created ON starts(created);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def session(self, token):
        if not token or len(token) > 128:
            return None
        owner = digest(token)
        with self.connect() as db:
            row = db.execute("SELECT expires FROM sessions WHERE owner=?", (owner,)).fetchone()
        return owner if row and row[0] > time.time() else None

    def new_session(self):
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM sessions WHERE expires < ?", (now,))
            db.execute("DELETE FROM runs WHERE created < ? OR owner NOT IN (SELECT owner FROM sessions)",
                       (now - SESSION_SECONDS,))
            if db.execute("SELECT count(*) FROM sessions").fetchone()[0] >= 2000:
                raise CapacityError("Session capacity reached. Try again later.")
            token = secrets.token_urlsafe(32)
            db.execute("INSERT INTO sessions VALUES (?,?)", (digest(token), now + SESSION_SECONDS))
        return token

    def admit(self, owner, ip, live, daily_limit):
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM starts WHERE created < ?", (now - 86400,))
            owner_count = db.execute("SELECT count(*) FROM starts WHERE owner=? AND created>?",
                                     (owner, now - 3600)).fetchone()[0]
            ip_count = db.execute("SELECT count(*) FROM starts WHERE ip=? AND created>?",
                                  (ip, now - 3600)).fetchone()[0]
            live_count = db.execute("SELECT count(*) FROM starts WHERE live=1").fetchone()[0]
            if owner_count >= 10 or ip_count >= 30 or (live and live_count >= daily_limit):
                raise CapacityError("Run quota reached. Try again later.")
            db.execute("INSERT INTO starts VALUES (?,?,?,?)", (owner, ip, int(live), now))

    def save(self, owner, payload):
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM runs WHERE created < ?", (now - SESSION_SECONDS,))
            db.execute("INSERT INTO runs VALUES (?,?,?,?)",
                       (payload["run_id"], owner, now, json.dumps(payload, ensure_ascii=False)))
            # Bounded storage: retain the latest 500 runs globally, at most 50 per session.
            db.execute("DELETE FROM runs WHERE owner=? AND id NOT IN "
                       "(SELECT id FROM runs WHERE owner=? ORDER BY created DESC LIMIT 50)", (owner, owner))
            db.execute("DELETE FROM runs WHERE id NOT IN (SELECT id FROM runs ORDER BY created DESC LIMIT 500)")

    def get(self, owner, run_id):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM runs WHERE owner=? AND id=? AND created>?",
                             (owner, run_id, time.time() - SESSION_SECONDS)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, owner):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM runs WHERE owner=? AND created>? "
                              "ORDER BY created DESC LIMIT 50", (owner, time.time() - SESSION_SECONDS)).fetchall()
        return [{key: payload.get(key) for key in ["run_id", "created_at", "mode", "status", "summary", "metrics"]}
                for row in rows for payload in [json.loads(row[0])]]

    def delete(self, owner, run_id):
        with self.connect() as db:
            return db.execute("DELETE FROM runs WHERE owner=? AND id=?", (owner, run_id)).rowcount > 0


def csv_cell(value):
    text = "" if value is None else str(value)
    # Spreadsheet formula injection includes leading whitespace/control characters.
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def export_csv(payload):
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    columns = ["company_name", "website", "profile_url", "score", "qualification_status",
               "score_reason", "email_status", "email_draft"]
    writer.writerow(columns + ["sources", "criteria", "facts"])
    for lead in payload.get("leads", []):
        values = [lead.get(key) for key in columns]
        values.extend(json.dumps(lead.get(key, []), ensure_ascii=False) for key in ["sources", "criteria", "facts"])
        writer.writerow([csv_cell(value) for value in values])
    return out.getvalue()
