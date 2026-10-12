import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sources (id INTEGER PRIMARY KEY, provider TEXT NOT NULL, board TEXT NOT NULL, company TEXT NOT NULL, UNIQUE(provider,board));
            CREATE TABLE IF NOT EXISTS evidence (id INTEGER PRIMARY KEY, category TEXT NOT NULL, title TEXT NOT NULL, text TEXT NOT NULL, source TEXT NOT NULL, verified INTEGER NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL, discovered_at TEXT NOT NULL, last_seen TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS applications (id INTEGER PRIMARY KEY, job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id), status TEXT NOT NULL, resume TEXT NOT NULL, snapshot TEXT NOT NULL, hash TEXT NOT NULL, model TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, receipt TEXT);
            CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, application_id INTEGER REFERENCES applications(id), kind TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
            ''')
            # A crash during network submission is ambiguous, never automatically retry it.
            rows = db.execute("SELECT id FROM applications WHERE status='submitting'").fetchall()
            for row in rows:
                db.execute("UPDATE applications SET status='unknown', updated_at=? WHERE id=?", (now(), row['id']))
                self.event(db, row['id'], 'unknown', 'Process restarted during submission. Verify with employer before doing anything further.')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def profile(self):
        from .models import Profile
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key='profile'").fetchone()
        return Profile.model_validate_json(row['value']) if row else Profile()

    def event(self, db, app_id, kind, detail):
        db.execute('INSERT INTO events(application_id,kind,detail,created_at) VALUES(?,?,?,?)', (app_id, kind, detail, now()))

    def upsert_jobs(self, jobs):
        with self.connect() as db:
            for job in jobs:
                db.execute('INSERT INTO jobs VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data,last_seen=excluded.last_seen', (job['id'], json.dumps(job), now(), now()))

    def job(self, id):
        with self.connect() as db:
            row = db.execute('SELECT data FROM jobs WHERE id=?', (id,)).fetchone()
        return json.loads(row['data']) if row else None

    def application(self, id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM applications WHERE id=?', (id,)).fetchone()
        return dict(row) if row else None
