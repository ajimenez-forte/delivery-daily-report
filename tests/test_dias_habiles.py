"""Días hábiles por país, días no hábiles de Forte, cierre de las 11:30 y promedio del equipo."""
import unittest
from datetime import date, datetime
from pathlib import Path

import psycopg2

from daily_report import metrics
from daily_report.import_json import load, run_import
from daily_report.users import add
from tests.pg import TestDB
from tests.test_import_json import data

ADMIN = "jefe.prueba@forteglobal.com"
ANA = "ana.prueba@forteglobal.com"
HISTORY = Path(__file__).resolve().parent.parent / "daily_historia_2026-08-27_a_09-30.json"
BOGOTA_NOON_OCT1 = datetime.fromisoformat("2026-10-01T12:00:00-05:00")


class BusinessDaysTest(unittest.TestCase):
    def setUp(self):
        self.tdb = TestDB()
        self.addCleanup(self.tdb.close)
        o = self.tdb.owner
        run_import(o, data(), log=lambda *_: None, countries={"BB": "CR"})
        add(o, ADMIN, "admin")
        add(o, ANA, "member", "AA")
        self.co = o.execute("SELECT id FROM people WHERE code = 'AA'").fetchone()[0]
        self.cr = o.execute("SELECT id FROM people WHERE code = 'BB'").fetchone()[0]

    def biz(self, pid, day):
        return self.tdb.owner.execute("SELECT is_business_day(?, ?::date)", (pid, day)).fetchone()[0]

    def prev(self, pid, day):
        return self.tdb.owner.execute("SELECT previous_business_day(?, ?::date)", (pid, day)).fetchone()[0]

    def test_weekends_and_country_holidays(self):
        self.assertFalse(self.biz(self.co, "2026-10-03"))   # sábado
        self.assertFalse(self.biz(self.co, "2026-10-04"))   # domingo
        self.assertFalse(self.biz(self.co, "2026-10-12"))   # festivo en Colombia
        self.assertTrue(self.biz(self.cr, "2026-10-12"))    # en Costa Rica es día hábil
        self.assertFalse(self.biz(self.cr, "2026-09-15"))   # independencia de Costa Rica
        self.assertTrue(self.biz(self.co, "2026-09-15"))

    def test_previous_business_day(self):
        self.assertEqual(self.prev(self.co, "2026-10-05"), date(2026, 10, 2))    # lunes -> viernes
        self.assertEqual(self.prev(self.co, "2026-10-13"), date(2026, 10, 9))    # tras lunes festivo
        self.assertEqual(self.prev(self.cr, "2026-10-13"), date(2026, 10, 12))   # CR no tiene ese festivo

    def test_forte_days_add_and_remove(self):
        admin = self.tdb.session(ADMIN)
        admin.execute("INSERT INTO forte_non_working_days (day, name, created_by) "
                      "VALUES ('2026-10-02', 'Día de integración', app_user_email())")
        admin.commit()
        self.assertFalse(self.biz(self.co, "2026-10-02"))
        self.assertFalse(self.biz(self.cr, "2026-10-02"))
        self.assertEqual(self.prev(self.co, "2026-10-05"), date(2026, 10, 1))
        admin.execute("DELETE FROM forte_non_working_days WHERE day = '2026-10-02'")
        admin.commit()
        self.assertTrue(self.biz(self.co, "2026-10-02"))

    def test_members_read_but_cannot_edit_calendar(self):
        ana = self.tdb.session(ANA)
        self.assertGreater(ana.execute("SELECT COUNT(*) FROM holidays").fetchone()[0], 0)
        with self.assertRaises(psycopg2.Error):
            ana.execute("INSERT INTO forte_non_working_days (day, name) VALUES ('2026-10-02', 'x')")
        ana.rollback()
        ana.execute("DELETE FROM holidays")
        ana.commit()
        self.assertGreater(self.tdb.owner.execute("SELECT COUNT(*) FROM holidays").fetchone()[0], 0)

    def test_report_window_closes_at_1130_bogota(self):
        q = "SELECT last_closed_day(?::timestamptz)"
        self.assertEqual(self.tdb.owner.execute(q, ("2026-10-01T11:29:00-05:00",)).fetchone()[0], date(2026, 9, 30))
        self.assertEqual(self.tdb.owner.execute(q, ("2026-10-01T11:30:00-05:00",)).fetchone()[0], date(2026, 10, 1))
        # Hoy antes de las 11:30 todavía no cuenta como día disponible.
        r = lambda now: next(x for x in metrics.table(self.tdb.owner, date(2026, 9, 8), date(2026, 9, 14), now=now)
                             ["filas"] if x["persona"] == "Ana Prueba")
        self.assertEqual(r(datetime.fromisoformat("2026-09-14T11:00:00-05:00"))["dias_disponibles"], 3)
        self.assertEqual(r(datetime.fromisoformat("2026-09-14T12:00:00-05:00"))["dias_disponibles"], 4)


class TeamAverageTest(unittest.TestCase):
    def setUp(self):
        self.tdb = TestDB()
        self.addCleanup(self.tdb.close)
        o = self.tdb.owner
        run_import(o, load(HISTORY), log=lambda *_: None)
        self.members = {}
        for code in ("LT", "MA", "NG", "RV", "SH", "VG"):
            email = f"{code.lower()}.prueba@forteglobal.com"
            add(o, email, "member", code)
            self.members[code] = email
        add(o, ADMIN, "admin")

    def avg(self, conn):
        return [dict(r) for r in conn.execute(
            "SELECT * FROM promedio_equipo_semanal('2026-09-07'::date, '2026-09-30'::date, ?::timestamptz)",
            (BOGOTA_NOON_OCT1.isoformat(),))]

    def test_member_gets_aggregate_but_not_others(self):
        lt = self.tdb.session(self.members["LT"])
        weeks = self.avg(lt)
        self.assertEqual(len(weeks), 4)
        self.assertTrue(all(w["tasa_reporte"] is not None for w in weeks))
        own = metrics.table(lt, date(2026, 9, 7), date(2026, 9, 30), now=BOGOTA_NOON_OCT1)["filas"]
        self.assertEqual([r["persona"] for r in own], ["Laura Torre"])

    def test_average_hidden_with_fewer_than_three_people(self):
        o = self.tdb.owner
        o.execute("UPDATE users SET active = false WHERE email NOT IN (?, ?, ?)",
                  (self.members["LT"], self.members["MA"], ADMIN))
        o.commit()
        weeks = self.avg(self.tdb.session(self.members["LT"]))
        self.assertTrue(all(w["tasa_reporte"] is None and w["cumplimiento"] is None for w in weeks))

    def test_unknown_user_gets_nothing(self):
        self.assertEqual(self.avg(self.tdb.session("no.listado@forteglobal.com")), [])


class HistoryRegressionTest(unittest.TestCase):
    """Los números aprobados del 27 de agosto al 29 de septiembre no cambian con días hábiles."""

    APPROVED = {  # persona: (días con reporte, disponibles, hechos, marcados)
        "Ma. Alejandra Valencia": (12, 24, 26, 29), "Laura Torre": (13, 22, 24, 30),
        "Nicole Gallego": (14, 22, 18, 25), "Valeria Gómez": (19, 24, 33, 45),
        "Ricardo Vergara": (9, 19, 42, 88), "Sandra Heredia": (18, 22, 14, 28),
    }

    def test_approved_numbers(self):
        tdb = TestDB()
        self.addCleanup(tdb.close)
        run_import(tdb.owner, load(HISTORY), log=lambda *_: None)
        add(tdb.owner, ADMIN, "admin")
        rows = metrics.table(tdb.session(ADMIN), date(2026, 8, 27), date(2026, 9, 29), now=BOGOTA_NOON_OCT1)["filas"]
        got = {r["persona"]: (r["dias_reporte"], r["dias_disponibles"], r["hechos"], r["marcados"]) for r in rows}
        self.assertEqual(got, self.APPROVED)
        laura = next(r for r in rows if r["persona"] == "Laura Torre")
        # El 15 de septiembre es feriado en Costa Rica: ya no cuenta como PTO.
        self.assertEqual(laura["dias_pto"], 1)


if __name__ == "__main__":
    unittest.main()


class TimezoneTest(unittest.TestCase):
    """Laura (Costa Rica) cierra a las 11:30 en su hora; el resto, en hora de Bogotá."""

    def setUp(self):
        self.tdb = TestDB()
        self.addCleanup(self.tdb.close)
        o = self.tdb.owner
        run_import(o, data(), log=lambda *_: None, countries={"BB": "CR"})
        add(o, "bb.prueba@forteglobal.com", "member", "BB")    # toma America/Costa_Rica por su país
        add(o, ANA, "member", "AA")
        self.co = o.execute("SELECT id FROM people WHERE code = 'AA'").fetchone()[0]
        self.cr = o.execute("SELECT id FROM people WHERE code = 'BB'").fetchone()[0]

    def one(self, sql, *args):
        return self.tdb.owner.execute(sql, args).fetchone()[0]

    def test_default_timezone_from_country(self):
        self.assertEqual(self.one("SELECT person_timezone(?)", self.cr), "America/Costa_Rica")
        self.assertEqual(self.one("SELECT person_timezone(?)", self.co), "America/Bogota")

    def test_cutoff_uses_person_time(self):
        # 12:00 en Bogotá = 11:00 en Costa Rica: para Laura todavía no cerró.
        now = "2026-09-14T12:00:00-05:00"
        days = lambda pid: [r[0] for r in self.tdb.owner.execute(
            "SELECT day FROM business_days(?, '2026-09-14'::date, '2026-09-14'::date, ?::timestamptz)", (pid, now))]
        self.assertEqual(days(self.co), [date(2026, 9, 14)])
        self.assertEqual(days(self.cr), [])
        later = "2026-09-14T12:30:00-05:00"   # 11:30 en Costa Rica
        self.assertEqual([r[0] for r in self.tdb.owner.execute(
            "SELECT day FROM business_days(?, '2026-09-14'::date, '2026-09-14'::date, ?::timestamptz)",
            (self.cr, later))], [date(2026, 9, 14)])

    def test_today_and_yesterday_in_person_time(self):
        # 00:30 del martes en Bogotá = 23:30 del lunes en Costa Rica.
        now = "2026-10-06T00:30:00-05:00"
        self.assertEqual(self.one("SELECT person_today(?, ?::timestamptz)", self.co, now), date(2026, 10, 6))
        self.assertEqual(self.one("SELECT person_today(?, ?::timestamptz)", self.cr, now), date(2026, 10, 5))
        self.assertEqual(self.one("SELECT person_yesterday(?, ?::timestamptz)", self.co, now), date(2026, 10, 5))
        self.assertEqual(self.one("SELECT person_yesterday(?, ?::timestamptz)", self.cr, now), date(2026, 10, 2))
