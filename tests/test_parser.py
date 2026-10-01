import unittest

from daily_report.parser import monday_key, parse_structured, slack_to_text

M = "https://forteglobal-squad.monday.com/boards/111/pulses/9001"


def parse(t, strict=False):
    return parse_structured(slack_to_text(t), strict=strict)


class ParserTest(unittest.TestCase):
    def test_sections_marks_and_links(self):
        p = parse(f"_Ayer:_\n• Reporte <{M}|x> - :white_check_mark: hecho\n"
                  "• Otra cosa :white_large_square: no lo toqué\n"
                  f"_Compromisos de hoy:_\n• Cerrar pagos → <{M}|x>\n• Sin link\n"
                  "_Operación:_ Intercom\n_Bloqueos:_ Firma pendiente, nivel 3")
        ayer = [c for c in p.commitments if c["section"] == "ayer"]
        hoy = [c for c in p.commitments if c["section"] == "hoy"]
        self.assertEqual([(c["text"], c["mark"]) for c in ayer], [("Reporte", "hecho"), ("Otra cosa", "no_tocado")])
        self.assertEqual(hoy[0]["monday_key"], "111:9001")
        self.assertIsNone(hoy[1]["monday_url"])
        self.assertEqual([o["text"] for o in p.operation], ["Intercom"])
        self.assertEqual(p.blockers[0]["decision_level"], 3)
        self.assertEqual(p.review, [])

    def test_doubtful_lines_go_to_review(self):
        p = parse("_Ayer:_\n• Tarea A - COMPLETADO\n• Tarea B\n• Tarea C ✅ 🔄\n• Taxes. Poco avance\n"
                  "_Hoy:_\n• Tarea D ✅")
        reasons = sorted(r["reason"] for r in p.review)
        self.assertEqual(reasons, sorted(["usa una marca no oficial", "sin marca", "tiene más de una marca",
                                          "usa una marca no oficial", "compromiso de hoy con marca"]))
        self.assertEqual(p.commitments, [])

    def test_word_mark(self):
        p = parse("Ayer:\n• Reunión de IA — hecho\n• Prueba — hecho (con 4 proveedores)\n"
                  "• Pagos — pendiente (avancé, no cerré)")
        self.assertEqual([c["mark"] for c in p.commitments], ["hecho", "hecho", "pendiente"])
        self.assertTrue(all(c["mark_source"] == "palabra" for c in p.commitments))
        self.assertEqual(len(parse("Ayer:\n• Reunión de IA — hecho", strict=True).review), 1)

    def test_group_labels_and_bulleted_headers(self):
        p = parse("• Compromisos de ayer:\n• BAHAMAS:\n• Reportes semanales ✅ hecho\n"
                  "• Operación\nHoy:\nCosta Rica:\n• Mensaje CR")
        self.assertEqual(p.commitments[0]["grp"], "BAHAMAS")
        self.assertEqual(p.commitments[-1]["grp"], "Costa Rica")
        # "• Operación" suelto en Ayer no es encabezado: queda como línea sin marca.
        self.assertEqual([r["reason"] for r in p.review], ["sin marca"])

    def test_preamble_and_not_a_report(self):
        self.assertFalse(parse("Gracias!").recognized)
        p = parse("Buenos días\nAyer:\n• X ✅")
        self.assertEqual(p.review[0]["reason"], "texto antes de las secciones")

    def test_board_only_key(self):
        self.assertEqual(monday_key("https://x.monday.com/boards/222"), "222")


if __name__ == "__main__":
    unittest.main()


class ReadOnlyClientTest(unittest.TestCase):
    def test_refuses_write_methods(self):
        from daily_report.slack_client import ReadOnlySlackClient, SlackError
        c = ReadOnlySlackClient(token="x")
        with self.assertRaises(SlackError):
            c._get("chat.postMessage", {"channel": "C1", "text": "hola"})


class RealShapesTest(unittest.TestCase):
    def test_label_with_parenthesis_is_removed(self):
        p = parse(f"Ayer:\n• Payment review: (<{M}|x>) :arrows_counterclockwise: pendiente (avancé, no cerré)")
        self.assertEqual(p.commitments[0]["text"], "Payment review")

    def test_status_written_in_hoy_goes_to_review(self):
        p = parse(f"Hoy:\n• Subir reporte → (<{M}|x>) Hecho\n• Doc SA (<{M}|x>) EN PROGRESO HASTA FIN DE MES")
        self.assertEqual([r["reason"] for r in p.review], ["compromiso de hoy con un estado escrito"] * 2)
