"""Esquema SQLite. La app y la importación comparten estas tablas.

Todo registro que viene de Slack lleva origin='slack' y el ts del mensaje
original (slack_ts) para poder volver a revisarlo.
"""
import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
    id            INTEGER PRIMARY KEY,
    slack_user_id TEXT UNIQUE,
    name          TEXT NOT NULL
);

-- Un día de Daily = un hilo "Daily Delivery —" (o un día en la app).
CREATE TABLE IF NOT EXISTS days (
    id        INTEGER PRIMARY KEY,
    day       TEXT NOT NULL UNIQUE,          -- YYYY-MM-DD, hora de Bogotá
    origin    TEXT NOT NULL,                 -- 'slack' | 'app'
    slack_ts  TEXT UNIQUE,                   -- ts del mensaje "Daily Delivery —"
    format    TEXT NOT NULL                  -- 'libre' | 'marcas' | 'app'
);

CREATE TABLE IF NOT EXISTS reports (
    id                    INTEGER PRIMARY KEY,
    day_id                INTEGER NOT NULL REFERENCES days(id),
    person_id             INTEGER NOT NULL REFERENCES people(id),
    origin                TEXT NOT NULL,     -- 'slack' | 'app'
    slack_ts              TEXT,              -- primer mensaje del reporte
    format                TEXT NOT NULL,     -- 'libre' | 'marcas' | 'app'
    raw_text              TEXT,              -- texto completo (siempre en 'libre')
    counts_for_rate       INTEGER NOT NULL DEFAULT 1,
    counts_for_compliance INTEGER NOT NULL DEFAULT 1,
    has_blockers_field    INTEGER NOT NULL DEFAULT 0,
    has_blockers          INTEGER NOT NULL DEFAULT 0,
    UNIQUE (day_id, person_id)
);

-- Cada mensaje de Slack que forma parte de un reporte.
CREATE TABLE IF NOT EXISTS report_messages (
    slack_ts   TEXT PRIMARY KEY,
    report_id  INTEGER NOT NULL REFERENCES reports(id),
    text_hash  TEXT NOT NULL,
    raw_text   TEXT NOT NULL
);

-- section: 'ayer' (estado de lo de ayer) | 'hoy' (compromiso nuevo)
-- mark: 'hecho' | 'pendiente' | 'no_tocado' | NULL (en 'hoy' no hay marca)
CREATE TABLE IF NOT EXISTS commitments (
    id            INTEGER PRIMARY KEY,
    report_id     INTEGER NOT NULL REFERENCES reports(id),
    section       TEXT NOT NULL,
    text          TEXT NOT NULL,
    grp           TEXT,                      -- "BAHAMAS:", "Costa Rica:"
    mark          TEXT,
    mark_source   TEXT,                      -- 'emoji' | 'palabra' | 'manual'
    is_extra      INTEGER NOT NULL DEFAULT 0,
    monday_url    TEXT,
    monday_key    TEXT,                      -- "board:pulse" o "board"
    link_status   TEXT NOT NULL,             -- 'con_link' | 'sin_link'
    streak_days   INTEGER NOT NULL DEFAULT 1,
    streak_prev_id INTEGER REFERENCES commitments(id),
    origin        TEXT NOT NULL,             -- 'slack' | 'app'
    slack_ts      TEXT,
    line_key      TEXT,                      -- clave estable de la línea
    manual        INTEGER NOT NULL DEFAULT 0,
    UNIQUE (slack_ts, line_key)
);

CREATE TABLE IF NOT EXISTS operation_items (
    id        INTEGER PRIMARY KEY,
    report_id INTEGER NOT NULL REFERENCES reports(id),
    text      TEXT NOT NULL,
    origin    TEXT NOT NULL,
    slack_ts  TEXT,
    line_key  TEXT,
    manual    INTEGER NOT NULL DEFAULT 0,
    UNIQUE (slack_ts, line_key)
);

CREATE TABLE IF NOT EXISTS blockers (
    id             INTEGER PRIMARY KEY,
    report_id      INTEGER NOT NULL REFERENCES reports(id),
    text           TEXT NOT NULL,
    decision_level INTEGER,
    origin         TEXT NOT NULL,
    slack_ts       TEXT,
    line_key       TEXT,
    manual         INTEGER NOT NULL DEFAULT 0,
    UNIQUE (slack_ts, line_key)
);

-- Líneas (o mensajes enteros) que no se pudieron interpretar con seguridad.
CREATE TABLE IF NOT EXISTS review_items (
    id            INTEGER PRIMARY KEY,
    kind          TEXT NOT NULL,             -- 'linea' | 'mensaje'
    slack_ts      TEXT NOT NULL,
    line_key      TEXT NOT NULL,
    day           TEXT NOT NULL,
    person_id     INTEGER REFERENCES people(id),
    section       TEXT,
    raw_text      TEXT NOT NULL,
    reason        TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pendiente', -- 'pendiente' | 'resuelto' | 'descartado'
    resolution    TEXT,                      -- JSON con lo que decidió el admin
    resolved_at   TEXT,
    stale         INTEGER NOT NULL DEFAULT 0, -- el mensaje original cambió
    UNIQUE (slack_ts, line_key)
);

CREATE TABLE IF NOT EXISTS import_runs (
    id          INTEGER PRIMARY KEY,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL,
    stats_json  TEXT
);

CREATE TABLE IF NOT EXISTS launch_approvals (
    id            INTEGER PRIMARY KEY,
    approved_at   TEXT NOT NULL,
    import_run_id INTEGER NOT NULL REFERENCES import_runs(id),
    summary_json  TEXT NOT NULL
);
"""


def connect(path=None):
    path = path or _default_path()
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def _default_path():
    from . import config
    return config.DB_PATH
