"""Conexión a Postgres (Supabase).

El esquema, las políticas RLS y las funciones de cálculo viven en
supabase/migrations/. Este módulo solo las aplica y da una conexión cómoda.

DATABASE_URL es la conexión del dueño de las tablas (en Supabase, la cadena
"Session pooler" con la contraseña de la base). La usan la importación y las
migraciones, y no pasa por RLS. La app nunca usa esta conexión: entra por la
API de Supabase con el token del usuario, y ahí RLS decide qué ve.
"""
import re
from pathlib import Path

import psycopg2
import psycopg2.extras

MIGRATIONS = Path(__file__).resolve().parent.parent / "supabase" / "migrations"


def migration_files():
    return sorted(MIGRATIONS.glob("*.sql"))


def migrate(conn):
    """Aplica todas las migraciones en orden. Son idempotentes."""
    for f in migration_files():
        conn.execute(f.read_text(encoding="utf-8"))
    conn.commit()


def _translate(sql):
    """Placeholders estilo '?' a los de psycopg2."""
    return re.sub(r"\?", "%s", sql.replace("%", "%%"))


class Result:
    def __init__(self, cur):
        self._cur = cur

    def fetchone(self):
        return self._cur.fetchone() if self._cur.description else None

    def fetchall(self):
        return self._cur.fetchall() if self._cur.description else []

    def __iter__(self):
        return iter(self.fetchall())


class Conn:
    """Envoltorio pequeño para que el resto del código use ? y filas por nombre."""

    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, params=()):
        cur = self.raw.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(_translate(sql) if params else sql, tuple(params) if params else None)
        return Result(cur)

    def insert(self, sql, params=()):
        """INSERT que devuelve el id de la fila nueva."""
        return self.execute(sql.rstrip().rstrip(";") + " RETURNING id", params).fetchone()[0]

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()


def connect(url=None):
    """Conexión del dueño (importación, migraciones)."""
    from . import config
    url = url or config.DATABASE_URL
    if not url:
        raise SystemExit("Falta DATABASE_URL (conexión de Postgres del dueño). Ver docs/SUPABASE.md.")
    return Conn(psycopg2.connect(url, client_encoding="utf8"))
