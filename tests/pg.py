"""Base de prueba en Postgres. Cada prueba usa una base nueva y la borra al final.

Necesita DAILY_TEST_DATABASE_URL con un usuario que pueda crear bases y roles,
por ejemplo: postgresql://postgres@/postgres?host=/tmp/pgdaily&port=55432
"""
import os
import uuid

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

from daily_report import db

APP_ROLE = "daily_app_test"


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
        cur = self.admin.cursor()
        cur.execute(f"CREATE DATABASE {self.name} ENCODING 'UTF8' TEMPLATE template0")
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_ROLE,))
        if not cur.fetchone():
            cur.execute(f"CREATE ROLE {APP_ROLE} LOGIN NOSUPERUSER NOBYPASSRLS")
        self.url = _with_db(_admin_url(), self.name)
        self.owner = db.connect(self.url)
        db.migrate(self.owner, app_role=APP_ROLE)

    def app_url(self):
        u = self.url.replace("://postgres@", f"://{APP_ROLE}@")
        assert APP_ROLE in u, "La URL de prueba debe usar el usuario postgres"
        return u

    def app(self, email):
        return db.connect_app(email, self.app_url())

    def close(self):
        self.owner.close()
        cur = self.admin.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS {self.name} WITH (FORCE)")
        self.admin.close()
