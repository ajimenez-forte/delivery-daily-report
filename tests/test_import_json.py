"""Importación desde el archivo de historia. Datos inventados, nombres ficticios."""
import copy
import unittest

from daily_report import bridge, db, review, summary
from daily_report.import_json import run_import

L = "https://forteglobal-squad.monday.com/boards/1/pulses/"


def c(texto, link=None, fecha=None):
    return {"texto": texto, "link_monday": link, "fecha_cierre_declarada": fecha}


def a(marca, texto, link=None, nota=None):
    return {"marca": marca, "texto": texto, "link_monday": link, "nota": nota}


def rep(persona, compromisos, ayer=(), extras=(), bloqueos="sin_bloqueos"):
    return {"persona": persona, "ayer": list(ayer), "extras": list(extras), "compromisos": compromisos,
            "operacion": "Intercom", "bloqueos": {"estado": bloqueos, "nivel": None, "nota": None}}


def day(fecha, fmt, reportes, ts):
    return {"fecha": fecha, "formato": fmt, "slack_ts_disparador": ts, "reportes": reportes,
            "sin_reporte": [], "sin_reporte_excluyendo_pto": []}


def data():
    return {
        "meta": {"advertencias": []},
        "personas": [{"codigo": "AA", "nombre": "Ana Prueba", "correo": "x", "slack_id": "U1"},
                     {"codigo": "BB", "nombre": "Beto Prueba", "correo": "y", "slack_id": "U2"}],
        "pto": [{"persona": "AA", "fechas": ["2026-09-10"]}],
        "dias": [
            day("2026-09-08", "libre", [{"persona": "AA", "ayer_texto": "pagos", "hoy_texto": "cerrar",
                                         "bloqueos_texto": "Sin bloqueos"}], "100.1"),
            day("2026-09-09", "marcas", [
                rep("AA", [c("Reporte mensual EsHoy", L + "7"), c("Presentación informe EsHoy", L + "7"),
                           c("Cerrar pagos proveedores", L + "8")],
                    ayer=[a("hecho", "Algo"), a(None, "Taxes", nota="marca no oficial: Poco avance")]),
                rep("BB", [c("Tarea sin link")], bloqueos="campo_ausente")], "200.1"),
            # 10 sep: Ana en PTO, no reporta
            day("2026-09-10", "marcas", [rep("BB", [c("Tarea sin link.")])], "300.1"),
            day("2026-09-11", "marcas", [
                rep("AA", [c("Reporte mensual EsHoy septiembre", L + "7"), c("Cerrar pagos a proveedores", L + "8"),
                           c("Enviar factura", L + "9")],
                    ayer=[a("pendiente", "Reporte mensual EsHoy", L + "7")],
                    extras=[a(None, "Extra dudoso")]),
                rep("BB", [c("tarea sin link")])], "400.1"),
        ],
        "punto_de_partida": [
            {"persona": "AA", "nombre": "Ana Prueba", "fecha_ultimo_reporte": "2026-09-11",
             "ayer_en_la_app": [dict(c("Reporte mensual EsHoy septiembre", L + "7"), dias_seguidos_al_corte=2),
                                dict(c("Cerrar pagos a proveedores", L + "8"), dias_seguidos_al_corte=2)]},
            {"persona": "BB", "nombre": "Beto Prueba", "fecha_ultimo_reporte": "2026-09-11",
             "ayer_en_la_app": [dict(c("tarea sin link"), dias_seguidos_al_corte=3)]},
        ],
        "resumen": {"dias_importados": 4, "lineas_a_revision": 2},
    }


def rows(conn, sql, *args):
    return [dict(r) for r in conn.execute(sql, args)]


class JsonImportTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.data = data()
        run_import(self.conn, self.data, log=lambda *_: None)

    def pid(self, code):
        return self.conn.execute("SELECT id FROM people WHERE code = ?", (code,)).fetchone()[0]

    def streaks(self, code, day):
        return {r["text"]: r["streak_days"] for r in rows(
            self.conn, """SELECT c.text, c.streak_days FROM commitments c JOIN reports r ON r.id=c.report_id
                          JOIN days d ON d.id=r.day_id WHERE r.person_id=? AND d.day=? AND c.section='hoy'""",
            self.pid(code), day)}

    def test_free_format_counts_for_rate_only(self):
        r = rows(self.conn, "SELECT * FROM reports WHERE format='libre'")[0]
        self.assertEqual((r["counts_for_rate"], r["counts_for_compliance"]), (1, 0))
        self.assertEqual((r["origin"], r["slack_ts"]), ("slack", "100.1"))
        self.assertIn("Ayer: pagos", r["raw_text"])

    def test_null_marks_go_to_review_without_mark(self):
        rv = rows(self.conn, "SELECT raw_text, section, reason FROM review_items ORDER BY id")
        self.assertEqual([(x["raw_text"], x["section"]) for x in rv], [("Taxes", "ayer"), ("Extra dudoso", "extra")])
        self.assertEqual(rv[0]["reason"], "marca no oficial: Poco avance")
        self.assertEqual(rows(self.conn, "SELECT COUNT(*) n FROM commitments WHERE text IN ('Taxes','Extra dudoso')"),
                         [{"n": 0}])

    def test_shared_link_needs_similar_text(self):
        s = self.streaks("AA", "2026-09-11")
        self.assertEqual(s["Reporte mensual EsHoy septiembre"], 2)  # mismo link y texto parecido
        self.assertEqual(s["Enviar factura"], 1)                    # link distinto

    def test_pto_neither_breaks_nor_adds(self):
        # Ana reportó 9 y 11; el 10 tuvo PTO. Cuenta 2, no 3, y no se rompe.
        self.assertEqual(self.streaks("AA", "2026-09-11")["Cerrar pagos a proveedores"], 2)
        # Beto reportó los tres días: 3.
        self.assertEqual(self.streaks("BB", "2026-09-11")["tarea sin link"], 3)

    def test_starting_point(self):
        y = bridge.yesterday_for(self.conn, self.pid("AA"), "2026-10-01")
        self.assertEqual([x["text"] for x in y["commitments"]],
                         ["Reporte mensual EsHoy septiembre", "Cerrar pagos a proveedores"])
        avisos = summary.build_summary(self.conn)["avisos"]
        self.assertTrue(any("Enviar factura" in w for w in avisos))
        # 2 días en Slack: el primero en la app es el tercero.
        self.assertEqual(bridge.streak_preview(self.conn, self.pid("AA"), "2026-10-01",
                                               "Cerrar pagos a proveedores", L + "8"), 3)
        # "Enviar factura" no está en el punto de partida: no sigue la racha.
        self.assertEqual(bridge.streak_preview(self.conn, self.pid("AA"), "2026-10-01", "Enviar factura",
                                               L + "9"), 1)

    def test_blockers_field(self):
        b = {r["code"]: (r["has_blockers_field"], r["blockers_status"]) for r in rows(
            self.conn, """SELECT p.code, r.has_blockers_field, r.blockers_status FROM reports r
                          JOIN people p ON p.id=r.person_id JOIN days d ON d.id=r.day_id WHERE d.day='2026-09-09'""")}
        self.assertEqual(b, {"AA": (1, "sin_bloqueos"), "BB": (0, "campo_ausente")})

    def test_idempotent_and_manual_fix_survives(self):
        item = rows(self.conn, "SELECT id FROM review_items WHERE raw_text='Taxes'")[0]["id"]
        review.resolve(self.conn, item, "compromiso", text="Taxes", section="ayer", mark="pendiente")
        tables = ("people", "days", "reports", "commitments", "operation_items", "blockers", "review_items", "pto")
        before = {t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
        run_import(self.conn, copy.deepcopy(self.data), log=lambda *_: None)
        after = {t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
        self.assertEqual(before, after)
        m = rows(self.conn, "SELECT mark, manual, origin FROM commitments WHERE text='Taxes'")
        self.assertEqual(m, [{"mark": "pendiente", "manual": 1, "origin": "slack"}])

    def test_summary_against_file(self):
        s = summary.build_summary(self.conn, self.data)
        self.assertEqual(s["contra_archivo"], [])
        ana = next(p for p in s["reportes_por_persona"] if p["persona"] == "Ana Prueba")
        self.assertEqual((ana["total"], ana["dias_pto"], ana["dias_habiles_sin_pto"]), (3, 1, 3))
        summary.format_summary(s)


class SlackImporterDisabledTest(unittest.TestCase):
    def test_main_refuses_without_flag(self):
        from daily_report import importer
        self.assertEqual(importer.main(["--db", ":memory:"]), 2)


if __name__ == "__main__":
    unittest.main()
