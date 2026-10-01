"""Base para las pruebas de punta a punta de la app (web/tests/e2e).

    python -m tests.e2e_db create   # imprime JSON con la base y los usuarios
    python -m tests.e2e_db drop NOMBRE

Usa DAILY_TEST_DATABASE_URL, igual que las pruebas de Python.
"""
import json
import os
import sys
from pathlib import Path

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

from daily_report.import_json import load, run_import
from daily_report.users import add
from tests.pg import TestDB, _admin_url

HISTORY = Path(__file__).resolve().parent.parent / "daily_historia_2026-08-27_a_09-30.json"
USERS = {
    "jefe.prueba@forteglobal.com": ("admin", None),
    "otro.admin@forteglobal.com": ("admin", None),
    "laura.prueba@forteglobal.com": ("member", "LT"),
    "nicole.prueba@forteglobal.com": ("member", "NG"),
}


def create():
    t = TestDB()
    run_import(t.owner, load(HISTORY), log=lambda *_: None)
    for email, (role, code) in USERS.items():
        add(t.owner, email, role, code)
    # Otro dominio que sí está en la lista como admin: no debe entrar nunca.
    t.owner.execute("INSERT INTO users (email, role) VALUES ('intruso@gmail.com', 'admin')")
    # En CI la base pide contraseña por TCP: PostgREST entra como authenticator con esta.
    if os.environ.get("E2E_AUTHENTICATOR_PASSWORD"):
        t.owner.execute(f"ALTER ROLE authenticator PASSWORD '{os.environ['E2E_AUTHENTICATOR_PASSWORD']}'")
    t.owner.commit()
    ids = {e: t.auth_user(e) for e in [*USERS, "intruso@gmail.com", "no.listado@forteglobal.com"]}
    people = {r["code"]: r["id"] for r in t.owner.execute("SELECT id, code FROM people")}
    out = {"name": t.name, "url": t.url, "users": ids, "people": people}
    t.owner.close()
    t.admin.close()
    print(json.dumps(out))


def drop(name):
    conn = psycopg2.connect(_admin_url())
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    conn.cursor().execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
    conn.close()


if __name__ == "__main__":
    create() if sys.argv[1] == "create" else drop(sys.argv[2])
