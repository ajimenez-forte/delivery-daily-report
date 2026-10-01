"""Identidad desde el token de Supabase, dominio, lista permitida y hook de registro."""
import json
import unittest
import uuid

import psycopg2

from daily_report.import_json import run_import
from daily_report.users import add
from tests.pg import TestDB
from tests.test_import_json import data

ADMIN = "jefe.prueba@forteglobal.com"
ANA = "ana.prueba@forteglobal.com"


class _Base(unittest.TestCase):
    def setUp(self):
        self.tdb = TestDB()
        self.addCleanup(self.tdb.close)
        o = self.tdb.owner
        run_import(o, data(), log=lambda *_: None)
        add(o, ADMIN, "admin")
        add(o, ANA, "member", "AA")

    def assert_no_access(self, conn, msg=""):
        self.assertFalse(conn.execute("SELECT app_is_user()").fetchone()[0], msg)
        self.assertFalse(conn.execute("SELECT app_is_admin()").fetchone()[0], msg)
        for t in ("people", "users", "days", "reports", "commitments", "review_items", "holidays"):
            self.assertEqual(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0], 0, f"{msg} {t}")


class IdentityTest(_Base):
    def test_valid_sessions(self):
        self.assertTrue(self.tdb.session(ADMIN).execute("SELECT app_is_admin()").fetchone()[0])
        ana = self.tdb.session(ANA)
        self.assertTrue(ana.execute("SELECT app_is_user()").fetchone()[0])
        self.assertFalse(ana.execute("SELECT app_is_admin()").fetchone()[0])

    def test_email_case_does_not_matter(self):
        self.assertTrue(self.tdb.session("Jefe.Prueba@ForteGlobal.com").execute("SELECT app_is_admin()").fetchone()[0])

    def test_other_domain_listed_as_admin_is_rejected(self):
        o = self.tdb.owner
        o.execute("INSERT INTO users (email, role) VALUES ('jefe@gmail.com', 'admin')")
        o.execute("INSERT INTO users (email, role) VALUES ('jefe@forteglobal.com.evil.com', 'admin')")
        o.commit()
        self.assert_no_access(self.tdb.session("jefe@gmail.com"), "gmail")
        self.assert_no_access(self.tdb.session("jefe@forteglobal.com.evil.com"), "subdominio falso")

    def test_unverified_email_is_rejected(self):
        self.assert_no_access(self.tdb.session("nuevo.prueba@forteglobal.com", verified=False), "sin verificar")
        self.tdb.auth_user(ADMIN)
        self.tdb.owner.execute("UPDATE auth.users SET email_confirmed_at = NULL WHERE email = ?", (ADMIN,))
        self.tdb.owner.commit()
        self.assert_no_access(self.tdb.session(ADMIN), "admin sin verificar")

    def test_not_in_allow_list_is_rejected(self):
        self.assert_no_access(self.tdb.session("no.listado@forteglobal.com"))

    def test_deactivated_user_is_rejected(self):
        self.tdb.owner.execute("UPDATE users SET active = false WHERE email = ?", (ADMIN,))
        self.tdb.owner.commit()
        self.assert_no_access(self.tdb.session(ADMIN))

    def test_token_email_must_match_auth_user(self):
        # Token de Ana (su sub) con el correo del admin: no coincide con auth.users.
        ana_id = self.tdb.auth_user(ANA)
        self.assert_no_access(self.tdb.session(claims={"sub": ana_id, "email": ADMIN, "role": "authenticated"}))
        # Correo del admin sin sub, o con un sub que no existe.
        self.assert_no_access(self.tdb.session(claims={"email": ADMIN, "role": "authenticated"}))
        self.assert_no_access(self.tdb.session(claims={"sub": str(uuid.uuid4()), "email": ADMIN}))

    def test_no_session(self):
        self.assert_no_access(self.tdb.session(claims={}))

    def test_anon_has_no_table_access(self):
        conn = self.tdb.session(claims={})
        conn.execute("RESET ROLE")
        conn.execute("SET ROLE anon")
        with self.assertRaises(psycopg2.Error):
            conn.execute("SELECT COUNT(*) FROM people")
        conn.rollback()

    def test_old_app_user_email_setting_is_ignored(self):
        """La identidad vieja (app.user_email) ya no sirve para nada."""
        conn = self.tdb.session(claims={})
        conn.execute("SELECT set_config('app.user_email', ?, false)", (ADMIN,))
        self.assert_no_access(conn)


class SignupHookTest(_Base):
    def hook(self, email):
        conn = self.tdb.session(claims={})
        conn.execute("RESET ROLE")
        conn.execute("SET ROLE supabase_auth_admin")
        event = {"metadata": {"name": "before-user-created"}, "user": {"email": email}}
        return conn.execute("SELECT hook_before_user_created(?::jsonb)", (json.dumps(event),)).fetchone()[0]

    def test_allows_listed_forte_accounts(self):
        self.assertEqual(self.hook(ANA), {})
        self.assertEqual(self.hook("ANA.PRUEBA@FORTEGLOBAL.COM"), {})

    def test_rejects(self):
        self.tdb.owner.execute("INSERT INTO users (email, role) VALUES ('alguien@gmail.com', 'admin')")
        self.tdb.owner.execute("UPDATE users SET active = false WHERE email = ?", (ADMIN,))
        self.tdb.owner.commit()
        for email in ("alguien@gmail.com", "x@forteglobal.com.evil.com", "a@b@forteglobal.com",
                      "no.listado@forteglobal.com", ADMIN, "", None):
            out = self.hook(email)
            self.assertEqual(out["error"]["http_code"], 403, email)

    def test_members_cannot_call_hook(self):
        with self.assertRaises(psycopg2.Error):
            self.tdb.session(ANA).execute("SELECT hook_before_user_created('{}'::jsonb)")


if __name__ == "__main__":
    unittest.main()
