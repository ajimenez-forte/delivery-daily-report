"""Usuarios y roles. Corre con la conexión del dueño (DATABASE_URL).

    python -m daily_report.users add correo@forteglobal.com admin
    python -m daily_report.users add correo@forteglobal.com member --persona LT
    python -m daily_report.users list
"""
import argparse
import sys

from . import db


def add(conn, email, role, person_code=None):
    pid = None
    if person_code:
        row = conn.execute("SELECT id FROM people WHERE code = ?", (person_code,)).fetchone()
        if not row:
            raise SystemExit(f"No existe la persona con código {person_code}")
        pid = row["id"]
    conn.execute("""INSERT INTO users (email, role, person_id) VALUES (?, ?, ?)
                    ON CONFLICT (email) DO UPDATE SET role = excluded.role, person_id = excluded.person_id""",
                 (email.strip().lower(), role, pid))
    conn.commit()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None, help="URL de Postgres del dueño (por defecto DATABASE_URL)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("email")
    a.add_argument("role", choices=["admin", "member"])
    a.add_argument("--persona", help="código de la persona (LT, NG...)")
    sub.add_parser("list")
    args = ap.parse_args(argv)
    conn = db.connect(args.db)
    db.migrate(conn)
    if args.cmd == "add":
        add(conn, args.email, args.role, args.persona)
    for r in conn.execute("SELECT u.email, u.role, p.name FROM users u LEFT JOIN people p ON p.id = u.person_id "
                          "ORDER BY u.role, u.email"):
        print(f"{r['role']:<7} {r['email']:<36} {r['name'] or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
