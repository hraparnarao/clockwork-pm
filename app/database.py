"""
ClockWork PM – database setup (SQLite via sqlite3, no ORM).
"""
import sqlite3
import os

DB_PATH = os.environ.get("CLOCKWORK_DB", "clockwork.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        name         TEXT NOT NULL,
        email        TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role         TEXT NOT NULL DEFAULT 'Employee',   -- Employee | Manager | Admin
        manager_id   INTEGER REFERENCES users(id),
        is_active    INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS projects (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        name      TEXT NOT NULL,
        client    TEXT,
        is_active INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS sub_projects (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        name       TEXT NOT NULL,
        is_active  INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS timesheet_entries (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL REFERENCES users(id),
        entry_date      TEXT NOT NULL,          -- ISO YYYY-MM-DD
        project_id      INTEGER NOT NULL REFERENCES projects(id),
        sub_project_id  INTEGER REFERENCES sub_projects(id),
        category        TEXT NOT NULL DEFAULT 'Billable',  -- Billable|Internal|Personal|Leave
        activity        TEXT,
        hours           REAL NOT NULL,
        status          TEXT NOT NULL DEFAULT 'Draft',     -- Draft|Submitted
        created_at      TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """)

    conn.commit()

    # ── Non-destructive migrations for existing databases ─────────────────────
    try:
        conn.execute("ALTER TABLE sub_projects ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        conn.commit()
    except Exception:
        pass  # column already exists

    conn.close()
