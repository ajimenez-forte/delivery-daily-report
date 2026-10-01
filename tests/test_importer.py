import unittest

from tests.pg import TestDB
from daily_report import bridge, db, review, summary
from daily_report.importer import run_import
from tests.fixtures import ANA, BETO, FakeClient, build


def rows(conn, sql, *a):
    return [dict(r) for r in conn.execute(sql, a)]


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.tdb = TestDB()
        self.addCleanup(self.tdb.close)
        self.conn = self.tdb.owner
        h, r = build()
        self.client = FakeClient(h, r)
        run_import(self.conn, self.client, "C1", log=lambda *_: None)

    def pid(self, uid):
        return self.conn.execute("SELECT id FROM people WHERE slack_user_id = ?", (uid,)).fetchone()[0]

    def test_only_read_methods(self):
        self.assertTrue(all(c[0] in ("conversations.history", "conversations.replies") for c in self.client.calls))

    def test_days_and_formats(self):
        days = rows(self.conn, "SELECT day, format, origin FROM days ORDER BY day")
        self.assertEqual([(d["day"], d["format"]) for d in days],
                         [("2026-08-27", "libre"), ("2026-09-09", "marcas"),
                          ("2026-09-10", "marcas"), ("2026-09-11", "marcas")])

    def test_free_text_counts_for_rate_not_compliance(self):
        r = rows(self.conn, "SELECT * FROM reports r JOIN days d ON d.id=r.day_id WHERE d.day='2026-08-27'")
        self.assertEqual(len(r), 1)  # Beto dijo "Gracias!" y el dueño no cuenta
        self.assertEqual((r[0]["counts_for_rate"], r[0]["counts_for_compliance"]), (1, 0))
        self.assertIn("armé el reporte", r[0]["raw_text"])
        self.assertEqual(r[0]["origin"], "slack")
        self.assertTrue(r[0]["slack_ts"])

    def test_chatter_goes_to_review_as_message(self):
        msgs = rows(self.conn, "SELECT raw_text FROM review_items WHERE kind='mensaje' ORDER BY day")
        self.assertEqual([m["raw_text"] for m in msgs], ["Gracias!", "Hola, hoy estoy en cita médica"])

    def test_streaks_link_and_text(self):
        hoy = rows(self.conn, """SELECT d.day, c.text, c.streak_days, c.link_status FROM commitments c
                                 JOIN reports r ON r.id=c.report_id JOIN days d ON d.id=r.day_id
                                 WHERE c.section='hoy' AND r.person_id=? ORDER BY d.day, c.id""", self.pid(ANA))
        got = {(h["day"], h["text"]): h["streak_days"] for h in hoy}
        # Por link (mismo pulse aunque cambie el texto)
        self.assertEqual(got[("2026-09-10", "Cerrar pagos a proveedores (W Learning)")], 2)
        self.assertEqual(got[("2026-09-11", "Cerrar pagos, versión final")], 3)
        # Por texto casi idéntico (sin link)
        self.assertEqual(got[("2026-09-10", "Hacer el reporte de Oxford")], 2)
        self.assertEqual(got[("2026-09-11", "hacer el reporte de oxford")], 3)
        self.assertEqual(got[("2026-09-10", "Nueva tarea")], 1)
        self.assertEqual({h["text"]: h["link_status"] for h in hoy}["Hacer el reporte de Oxford"], "sin_link")

    def test_idempotent(self):
        before = {t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("days", "reports", "commitments", "operation_items", "blockers", "review_items")}
        run_import(self.conn, self.client, "C1", log=lambda *_: None)
        run_import(self.conn, self.client, "C1", log=lambda *_: None)
        after = {t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in before}
        self.assertEqual(before, after)

    def test_manual_fix_survives_reimport_and_affects_streak(self):
        item = rows(self.conn, "SELECT id FROM review_items WHERE raw_text LIKE '%COMPLETADO%'")[0]
        review.resolve(self.conn, item["id"], "compromiso", text="Revisar tablero", section="ayer", mark="hecho")
        run_import(self.conn, self.client, "C1", log=lambda *_: None)
        c = rows(self.conn, "SELECT * FROM commitments WHERE manual=1")
        self.assertEqual(len(c), 1)
        self.assertEqual((c[0]["mark"], c[0]["origin"]), ("hecho", "slack"))
        st = rows(self.conn, "SELECT status FROM review_items WHERE id=?", item["id"])[0]
        self.assertEqual(st["status"], "resuelto")

    def test_blockers(self):
        b = rows(self.conn, "SELECT text, decision_level FROM blockers")
        self.assertEqual(b, [{"text": "Pago bloqueado por firma, nivel 4", "decision_level": 4}])

    def test_first_day_in_app(self):
        y = bridge.yesterday_for(self.conn, self.pid(ANA), "2026-10-02")
        self.assertEqual(y["day"], "2026-09-11")
        self.assertEqual([c["text"] for c in y["commitments"]],
                         ["Cerrar pagos, versión final", "hacer el reporte de oxford"])
        # Llevaba 3 días en Slack: el primero en la app es el cuarto.
        M1 = "https://forteglobal-squad.monday.com/boards/111/pulses/9001"
        self.assertEqual(bridge.streak_preview(self.conn, self.pid(ANA), "2026-10-02",
                                               "Cerrar pagos, versión final", M1), 4)
        # Mismo link pero otra tarea: no sigue la racha.
        self.assertEqual(bridge.streak_preview(self.conn, self.pid(ANA), "2026-10-02", "Cualquier texto", M1), 1)
        self.assertEqual(bridge.streak_preview(self.conn, self.pid(ANA), "2026-10-02", "Algo nuevo"), 1)

    def test_approval_gate(self):
        self.assertFalse(summary.launch_allowed(self.conn))
        summary.approve(self.conn)
        self.assertTrue(summary.launch_allowed(self.conn))
        run_import(self.conn, self.client, "C1", log=lambda *_: None)
        self.assertFalse(summary.launch_allowed(self.conn))  # nueva corrida pide aprobar de nuevo

    def test_summary(self):
        s = summary.build_summary(self.conn)
        self.assertEqual(s["dias_importados"]["total"], 4)
        self.assertEqual(s["dias_importados"]["texto_libre"], 1)
        self.assertGreater(s["revision"]["lineas_enviadas"], 0)
        names = {p["persona"]: p["total"] for p in s["reportes_por_persona"]}
        self.assertEqual(names, {"Ana Prueba": 4, "Beto Prueba": 1})
        summary.format_summary(s)


if __name__ == "__main__":
    unittest.main()
