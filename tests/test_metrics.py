"""Carga y cumplimiento: cálculo y Row Level Security."""
import unittest
from datetime import date

import psycopg2

from daily_report import db, metrics, review
from daily_report.import_json import run_import
from daily_report.users import add
from tests.pg import TestDB
from tests.test_import_json import L, a, c, data, day, rep

ADMIN, OTHER_ADMIN, ANA, NOBODY = "jefe@ejemplo.com", "otro@ejemplo.com", "ana@ejemplo.com", "nadie@ejemplo.com"


def metrics_data():
    d = data()
    # 14 sep: Ana con un ⬜ y un compromiso que llega al tercer día
    d["dias"].append(day("2026-09-14", "marcas", [rep(
        "AA", [c("Cerrar pagos a proveedores", L + "8")],
        ayer=[a("no_lo_toque", "Reporte mensual EsHoy septiembre", L + "7"), a("hecho", "Cerrar pagos", L + "8")],
        extras=[a("hecho", "Extra que no cuenta")])], "500.1"))
    d["punto_de_partida"] = []
    return d


class _Setup:
    def setUp(self):
        self.tdb = TestDB()
        self.addCleanup(self.tdb.close)
        o = self.tdb.owner
        run_import(o, metrics_data(), log=lambda *_: None)
        add(o, ADMIN, "admin")
        add(o, OTHER_ADMIN, "admin")
        add(o, ANA, "member", "AA")
        self.admin = self.tdb.app(ADMIN)
        self.addCleanup(self.admin.close)



class MetricsTest(_Setup, unittest.TestCase):
    def row(self, conn, name, start=date(2026, 9, 1), end=date(2026, 9, 30)):
        return next(r for r in metrics.table(conn, start, end)["filas"] if r["persona"] == name)

    def test_columns(self):
        r = self.row(self.admin, "Ana Prueba", date(2026, 9, 8), date(2026, 9, 14))
        # Días: 9/8 libre, 9/9, 9/11, 9/14 reportados; 9/10 PTO. 5 días - 1 PTO = 4.
        self.assertEqual((r["dias_reporte"], r["dias_disponibles"], r["dias_pto"]), (4, 4, 1))
        self.assertEqual(metrics.fmt_days(r), "4/4 (100.0%) (1 día de PTO)")
        # Compromisos de Hoy en días de marcas: 3 + 3 + 1 en 3 días.
        self.assertEqual(r["compromisos_por_dia"], 2.3)
        # Ayer marcados sin extras: 9/9 Algo ✅; 9/11 pendiente; 9/14 ⬜ y ✅. Taxes (null) no cuenta.
        self.assertEqual((r["hechos"], r["marcados"], r["sin_tocar"]), (2, 4, 1))
        self.assertEqual((r["pct_hechos"], r["pct_sin_tocar"]), (50.0, 25.0))
        # "Cerrar pagos" llegó al tercer día el 14 (9/9, 9/11, 9/14; el 10 fue PTO).
        self.assertEqual(r["alertas_tercer_dia"], 1)
        # Taxes (Ayer, null) y Extra dudoso (extra, null), pendientes en revisión.
        self.assertEqual(r["sin_marca"], 2)

    def test_null_line_counts_only_after_admin_assigns_mark(self):
        item = self.tdb.owner.execute("SELECT id FROM review_items WHERE raw_text = 'Taxes'").fetchone()[0]
        review.resolve(self.admin, item, "compromiso", text="Taxes", section="ayer", mark="hecho")
        r = self.row(self.admin, "Ana Prueba", date(2026, 9, 9), date(2026, 9, 14))
        self.assertEqual((r["hechos"], r["marcados"], r["sin_marca"]), (3, 5, 1))

    def test_libre_note_and_default_sort(self):
        t = metrics.table(self.admin, date(2026, 9, 1), date(2026, 9, 30))
        self.assertIn("1 días en formato libre", t["nota_libre"])
        self.assertIsNone(metrics.table(self.admin, date(2026, 9, 9), date(2026, 9, 30))["nota_libre"])
        pcts = [r["pct_hechos"] for r in t["filas"]]
        present = [p for p in pcts if p is not None]
        self.assertEqual(present, sorted(present, reverse=True))
        self.assertEqual(pcts[len(present):], [None] * (len(pcts) - len(present)))
        asc = metrics.table(self.admin, date(2026, 9, 1), date(2026, 9, 30), "persona", desc=False)
        self.assertEqual([r["persona"] for r in asc["filas"]], ["Ana Prueba", "Beto Prueba"])

    def test_weekly_and_csv(self):
        pid = self.tdb.owner.execute("SELECT id FROM people WHERE code='AA'").fetchone()[0]
        weeks = metrics.weekly(self.admin, pid, date(2026, 9, 1), date(2026, 9, 30))
        self.assertEqual([w["semana"] for w in weeks], ["2026-09-07", "2026-09-14"])
        self.assertEqual(weeks[1]["pct_sin_tocar"], 50.0)
        csv_text = metrics.to_csv(metrics.table(self.admin, date(2026, 9, 1), date(2026, 9, 30)))
        self.assertIn("Ana Prueba", csv_text)
        self.assertIn(metrics.DISCLAIMER, csv_text)

    def test_current_month_default(self):
        self.assertEqual(metrics.current_month(date(2026, 10, 1)), (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(metrics.parse_range({}, date(2026, 2, 10)), (date(2026, 2, 1), date(2026, 2, 28)))


class RowLevelSecurityTest(_Setup, unittest.TestCase):
    """La base filtra, no la interfaz: estas consultas van directo a Postgres."""

    def test_member_sees_only_own_rows(self):
        ana = self.tdb.app(ANA)
        self.addCleanup(ana.close)
        names = [r["persona"] for r in metrics.table(ana, date(2026, 9, 1), date(2026, 9, 30))["filas"]]
        self.assertEqual(names, ["Ana Prueba"])
        self.assertEqual(ana.execute("SELECT COUNT(DISTINCT person_id) FROM reports").fetchone()[0], 1)
        for t in ("review_items", "import_runs", "launch_approvals", "admin_notes"):
            self.assertEqual(ana.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0], 0, t)
        self.assertFalse(ana.execute("SELECT app_is_admin()").fetchone()[0])

    def test_unknown_user_sees_nothing(self):
        x = self.tdb.app(NOBODY)
        self.addCleanup(x.close)
        for t in ("people", "days", "reports", "commitments", "pto", "users"):
            self.assertEqual(x.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0], 0, t)

    def test_member_cannot_write_other_rows(self):
        ana = self.tdb.app(ANA)
        self.addCleanup(ana.close)
        beto = self.tdb.owner.execute("SELECT id FROM people WHERE code='BB'").fetchone()[0]
        ana.execute("UPDATE pto SET origin = 'x' WHERE person_id = ?", (beto,))
        ana.execute("DELETE FROM reports WHERE person_id = ?", (beto,))
        ana.commit()
        self.assertGreater(self.tdb.owner.execute("SELECT COUNT(*) FROM reports WHERE person_id = ?",
                                                  (beto,)).fetchone()[0], 0)
        self.assertEqual(self.tdb.owner.execute("SELECT COUNT(*) FROM pto WHERE origin='x'").fetchone()[0], 0)
        with self.assertRaises(psycopg2.Error):
            ana.execute("INSERT INTO admin_notes (person_id, author_email, body, updated_at) "
                        "VALUES (?, ?, 'x', 'now')", (beto, ANA))
        ana.rollback()

    def test_private_notes_only_for_author(self):
        pid = self.tdb.owner.execute("SELECT id FROM people WHERE code='BB'").fetchone()[0]
        metrics.save_note(self.admin, pid, "solo para mí")
        self.assertEqual(metrics.get_note(self.admin, pid)[0], "solo para mí")
        other = self.tdb.app(OTHER_ADMIN)
        self.addCleanup(other.close)
        self.assertEqual(metrics.get_note(other, pid)[0], "")
        self.assertEqual(other.execute("SELECT COUNT(*) FROM admin_notes").fetchone()[0], 0)
        # Ni escribiendo con el correo del autor.
        with self.assertRaises(psycopg2.Error):
            other.execute("INSERT INTO admin_notes (person_id, author_email, body, updated_at) "
                          "VALUES (?, ?, 'pisar', 'now') ON CONFLICT (person_id, author_email) "
                          "DO UPDATE SET body = 'pisar'", (pid, ADMIN))
        other.rollback()
        self.assertEqual(metrics.get_note(self.admin, pid)[0], "solo para mí")

    def test_app_role_does_not_bypass_rls(self):
        app = self.tdb.app(NOBODY)
        self.addCleanup(app.close)
        r = app.execute("SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()
        self.assertEqual((r[0], r[1]), (False, False))



class AdminServerTest(_Setup, unittest.TestCase):
    """El servidor responde 403 a quien no es admin, además de RLS."""

    def get(self, email, path, method="GET", origin=True):
        import threading
        import urllib.error
        import urllib.request
        from http.server import ThreadingHTTPServer
        from unittest import mock

        from daily_report import admin, config
        srv = ThreadingHTTPServer(("127.0.0.1", 0), admin.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        host = f"127.0.0.1:{srv.server_address[1]}"
        req = urllib.request.Request(f"http://{host}{path}", method=method, data=b"body=x" if method == "POST" else None,
                                     headers={"X-User": email, **({"Origin": f"http://{host}"} if origin else {})})
        with mock.patch.object(config, "AUTH_HEADER", "X-User"), \
                mock.patch.object(config, "APP_DATABASE_URL", self.tdb.app_url()):
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, r.read().decode()
            except urllib.error.HTTPError as ex:
                return ex.code, ex.read().decode()

    def test_access(self):
        q = "?desde=2026-09-01&hasta=2026-09-30"
        code, body = self.get(ADMIN, "/carga" + q)
        self.assertEqual(code, 200)
        self.assertIn("Beto Prueba", body)
        self.assertIn(metrics.DISCLAIMER, body)
        self.assertEqual(self.get(ADMIN, "/carga.csv" + q)[0], 200)
        for who in (ANA, NOBODY, ""):
            for path in ("/carga" + q, "/carga.csv" + q, "/persona?id=1", "/revision", "/"):
                self.assertEqual(self.get(who, path)[0], 403, (who, path))
        self.assertEqual(self.get(ANA, "/persona/1/notas", "POST")[0], 403)
        self.assertEqual(self.get(ADMIN, "/persona/1/notas", "POST", origin=False)[0], 403)
