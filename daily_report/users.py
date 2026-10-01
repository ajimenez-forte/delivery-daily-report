"""Usuarios y roles. Corre con la conexión del dueño (DATABASE_URL).

    python -m daily_report.users add correo@forteglobal.com admin
    python -m daily_report.users add correo@forteglobal.com member --persona LT
    python -m daily_report.users deactivate correo@forteglobal.com
    python -m daily_report.users list

Solo se aceptan correos @forteglobal.com. La base además lo exige al entrar.
"""
import argparse
import sys

from . import db


DOMAIN = "@forteglobal.com"


TIMEZONES = {"CO": "America/Bogota", "CR": "America/Costa_Rica"}


def add(conn, email, role, person_code=None, timezone=None):
    email = email.strip().lower()
    if not email.endswith(DOMAIN) or email.count("@") != 1:
        raise SystemExit(f"Solo se aceptan correos {DOMAIN}")
    pid, country = None, "CO"
    if person_code:
        row = conn.execute("SELECT id, country FROM people WHERE code = ?", (person_code,)).fetchone()
        if not row:
            raise SystemExit(f"No existe la persona con código {person_code}")
        pid, country = row["id"], row["country"]
    # Por defecto, la zona horaria sale del país de la persona.
    timezone = timezone or TIMEZONES.get(country, "America/Bogota")
    conn.execute("""INSERT INTO users (email, role, person_id, active, timezone) VALUES (?, ?, ?, true, ?)
                    ON CONFLICT (email) DO UPDATE SET role = excluded.role, person_id = excluded.person_id,
                      active = true, timezone = excluded.timezone""",
                 (email, role, pid, timezone))
    conn.commit()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None, help="URL de Postgres del dueño (por defecto DATABASE_URL)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("email")
    a.add_argument("role", choices=["admin", "member"])
    a.add_argument("--persona", help="código de la persona (LT, NG...)")
    a.add_argument("--zona", choices=sorted(set(TIMEZONES.values())),
                   help="zona horaria (por defecto, la del país de la persona)")
    d = sub.add_parser("deactivate")
    d.add_argument("email")
    sub.add_parser("list")
    args = ap.parse_args(argv)
    conn = db.connect(args.db)
    db.migrate(conn)
    if args.cmd == "add":
        add(conn, args.email, args.role, args.persona, args.zona)
    elif args.cmd == "deactivate":
        conn.execute("UPDATE users SET active = false WHERE email = ?", (args.email.strip().lower(),))
        conn.commit()
    for r in conn.execute("SELECT u.email, u.role, u.active, u.timezone, p.name FROM users u "
                          "LEFT JOIN people p ON p.id = u.person_id ORDER BY u.role, u.email"):
        print(f"{r['role']:<7} {'activo' if r['active'] else 'inactivo':<9} {r['timezone']:<19} "
              f"{r['email']:<36} {r['name'] or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
