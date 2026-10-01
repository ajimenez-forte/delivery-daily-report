"""Base de prueba en Postgres que imita Supabase. Cada prueba usa una base nueva.

Necesita DAILY_TEST_DATABASE_URL con un usuario que pueda crear bases y roles,
por ejemplo: postgresql://postgres@/postgres?host=/tmp/pgdaily&port=55432

Las migraciones son las mismas de supabase/migrations. Antes se aplica
tests/supabase_stub.sql, que crea el esquema auth y los roles de Supabase.

Una sesión de usuario se simula como lo hace PostgREST después de verificar el
token: la conexión pasa al rol `authenticated` y pone los claims del JWT en
request.jwt.claims. La firma del token no se prueba aquí: eso lo hace Supabase
y queda para las pruebas de la etapa 2 contra Supabase local.
"""
import json
import os
import uuid
from pathlib import Path

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

from daily_report import db

STUB = Path(__file__).resolve().parent / "supabase_stub.sql"


def _admin_url():
    url = os.environ.get("DAILY_TEST_DATABASE_URL")
    if not url:
        raise RuntimeError("Falta DAILY_TEST_DATABASE_URL para correr las pruebas (ver docs/IMPORTACION.md).")
    return url


def _with_db(url, name):
    base, _, query = url.partition("?")
    base = base.rsplit("/", 1)[0] + "/" + name
    return base + ("?" + query if query else "")


class TestDB:
    def __init__(self):
        self.name = "daily_test_" + uuid.uuid4().hex[:10]
        self.admin = psycopg2.connect(_admin_url())
        self.admin.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        self.admin.cursor().execute(f"CREATE DATABASE {self.name} ENCODING 'UTF8' TEMPLATE template0")
        self.url = _with_db(_admin_url(), self.name)
        self.owner = db.connect(self.url)
        self.owner.execute(STUB.read_text(encoding="utf-8"))
        db.migrate(self.owner)
        self._open = []

    def auth_user(self, email, verified=True):
        """Crea (o reutiliza) el usuario en auth.users, como lo haría el login con Google."""
        row = self.owner.execute("SELECT id FROM auth.users WHERE lower(email) = lower(?)", (email,)).fetchone()
        if row:
            return str(row[0])
        uid = str(uuid.uuid4())
        self.owner.execute("INSERT INTO auth.users (id, email, email_confirmed_at) VALUES (?, ?, ?)",
                           (uid, email, "2026-10-01T12:00:00Z" if verified else None))
        self.owner.commit()
        return uid

    def session(self, email=None, verified=True, claims=None):
        """Conexión como un usuario con sesión válida de Supabase.

        `claims` permite armar tokens raros (correo que no coincide, sin sub...).
        """
        if claims is None:
            uid = self.auth_user(email, verified) if email else None
            claims = {"sub": uid, "email": email, "role": "authenticated", "aud": "authenticated"}
        conn = db.Conn(psycopg2.connect(self.url, client_encoding="utf8"))
        conn.execute("SET ROLE authenticated")
        conn.execute("SELECT set_config('request.jwt.claims', ?, false)", (json.dumps(claims),))
        conn.commit()
        self._open.append(conn)
        return conn

    # Compatibilidad con las pruebas anteriores.
    def app(self, email):
        return self.session(email)

    def close(self):
        for c in self._open:
            try:
                c.close()
            except Exception:
                pass
        self.owner.close()
        self.admin.cursor().execute(f"DROP DATABASE IF EXISTS {self.name} WITH (FORCE)")
        self.admin.close()
