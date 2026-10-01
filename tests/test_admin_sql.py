"""Acciones del administrador en SQL: marcar líneas de revisión y aprobar la importación."""
import unittest
from datetime import date, datetime

import psycopg2

from daily_report import metrics
from daily_report.import_json import run_import
from daily_report.users import add
from tests.pg import TestDB
from tests.test_import_json import data

ADMIN, ANA = "jefe.prueba@forteglobal.com", "ana.prueba@forteglobal.com"
NOW = datetime.fromisoformat("2026-10-01T12:00:00-05:00")


class AdminSqlTest(unittest.TestCase):
    def setUp(self):
        self.tdb = TestDB()
        self.addCleanup(self.tdb.close)
        run_import(self.tdb.owner, data(), log=lambda *_: None)
        add(self.tdb.owner, ADMIN, "admin")
        add(self.tdb.owner, ANA, "member", "AA")
        self.admin = self.tdb.session(ADMIN)
        self.item = lambda txt: self.tdb.owner.execute("SELECT id FROM review_items WHERE raw_text = ?",
                                                       (txt,)).fetchone()[0]

    def ana_row(self):
        return next(r for r in metrics.table(self.admin, date(2026, 9, 9), date(2026, 9, 11), now=NOW)["filas"]
                    if r["persona"] == "Ana Prueba")

    def test_assign_mark_counts_ayer_only(self):
        before = self.ana_row()
        self.admin.execute("SELECT resolver_linea(?, 'hecho')", (self.item("Taxes"),))
        self.admin.execute("SELECT resolver_linea(?, 'hecho')", (self.item("Extra dudoso"),))
        self.admin.commit()
        after = self.ana_row()
        self.assertEqual(after["hechos"] - before["hechos"], 1)          # el extra no cuenta
        self.assertEqual(after["marcados"] - before["marcados"], 1)
        self.assertEqual(before["sin_marca"] - after["sin_marca"], 2)
        status = [r[0] for r in self.tdb.owner.execute("SELECT status FROM review_items ORDER BY id")]
        self.assertEqual(status, ["resuelto", "resuelto"])

    def test_reassign_replaces_previous_mark(self):
        i = self.item("Taxes")
        self.admin.execute("SELECT resolver_linea(?, 'hecho')", (i,))
        self.admin.execute("SELECT resolver_linea(?, 'no_tocado')", (i,))
        self.admin.commit()
        marks = [r[0] for r in self.tdb.owner.execute("SELECT mark FROM commitments WHERE manual = 1")]
        self.assertEqual(marks, ["no_tocado"])

    def test_discard_and_invalid_mark(self):
        self.admin.execute("SELECT descartar_linea(?)", (self.item("Taxes"),))
        self.admin.commit()
        with self.assertRaises(psycopg2.Error):
            self.admin.execute("SELECT resolver_linea(?, 'completado')", (self.item("Extra dudoso"),))
        self.admin.rollback()

    def test_member_cannot_use_admin_actions(self):
        ana = self.tdb.session(ANA)
        for sql in ("SELECT resolver_linea(1, 'hecho')", "SELECT descartar_linea(1)",
                    "SELECT aprobar_importacion('{}'::jsonb)"):
            with self.assertRaises(psycopg2.Error, msg=sql):
                ana.execute(sql)
            ana.rollback()

    def test_approval_is_reset_by_later_fix(self):
        state = lambda: dict(self.admin.execute("SELECT * FROM estado_aprobacion()").fetchone())
        self.assertFalse(state()["aprobado"])
        self.admin.execute("SELECT aprobar_importacion('{\"ok\": true}'::jsonb)")
        self.admin.commit()
        self.assertTrue(state()["aprobado"])
        # Misma regla que daily_report.summary: una corrección posterior obliga a aprobar otra vez.
        self.tdb.owner.execute("UPDATE review_items SET resolved_at = '2999-01-01T00:00:00+00:00' WHERE id = ?",
                               (self.item("Taxes"),))
        self.tdb.owner.commit()
        self.assertFalse(state()["aprobado"])


if __name__ == "__main__":
    unittest.main()
