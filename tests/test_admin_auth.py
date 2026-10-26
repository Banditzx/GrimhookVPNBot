from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from streamlit.testing.v1 import AppTest

from test_activation_codes import db, TEST_STORAGE
import admin_auth as auth


class AdminAuthTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=TEST_STORAGE.name)
        self.original = db.engine, db.Session, db.DB_PATH
        db.DB_PATH = Path(self.folder.name) / "admin.db"
        db.engine = create_engine(f"sqlite:///{db.DB_PATH}")
        db.Session = sessionmaker(bind=db.engine)
        db.Base.metadata.create_all(db.engine)
        auth.ensure_admin_account()

    def tearDown(self):
        db.engine.dispose()
        db.engine, db.Session, db.DB_PATH = self.original
        self.folder.cleanup()

    def test_default_account_is_seeded_once_and_password_is_hashed(self):
        account = auth.authenticate_admin("admin", "admin")
        self.assertIsNotNone(account)
        with db.Session() as session:
            record = session.query(db.AdminAccount).one()
            self.assertNotEqual(record.password_hash, "admin")
            original_hash = record.password_hash
        auth.ensure_admin_account()
        with db.Session() as session:
            self.assertEqual(session.query(db.AdminAccount).one().password_hash, original_hash)

    def test_invalid_username_password_and_disabled_account_are_rejected(self):
        for username, password in (("admin", "bad"), ("other", "admin"), ("' OR 1=1 --", "admin"), ("admin", "x" * 257)):
            self.assertIsNone(auth.authenticate_admin(username, password))
        with db.Session.begin() as session:
            session.query(db.AdminAccount).update({db.AdminAccount.is_active: False})
        self.assertIsNone(auth.authenticate_admin("admin", "admin"))

    def test_login_is_case_insensitive_and_ignores_surrounding_spaces(self):
        self.assertIsNotNone(auth.authenticate_admin(" ADMIN ", "admin"))

    def test_session_survives_reinitialization_and_token_is_not_stored(self):
        token = auth.create_admin_session(1)
        auth.ensure_admin_account()
        self.assertEqual(auth.get_admin_session(token)["username"], "admin")
        with db.Session() as session:
            self.assertNotEqual(session.query(db.AdminSession).one().token_hash, token)

    def test_expired_tampered_and_revoked_sessions_are_rejected(self):
        token = auth.create_admin_session(1)
        self.assertIsNone(auth.get_admin_session("x" * 43))
        with db.Session.begin() as session:
            session.query(db.AdminSession).update({db.AdminSession.expires_at: datetime.utcnow() - timedelta(seconds=1)})
        self.assertIsNone(auth.get_admin_session(token))
        token = auth.create_admin_session(1)
        auth.delete_admin_session(token)
        self.assertIsNone(auth.get_admin_session(token))

    def test_disabling_account_revokes_access_for_existing_session(self):
        token = auth.create_admin_session(1)
        with db.Session.begin() as session:
            session.query(db.AdminAccount).update({db.AdminAccount.is_active: False})
        self.assertIsNone(auth.get_admin_session(token))

    def test_changing_password_revokes_sessions_and_survives_bootstrap(self):
        token = auth.create_admin_session(1)
        self.assertTrue(auth.change_admin_password(1, "admin", "new-password-123"))
        self.assertIsNone(auth.get_admin_session(token))
        auth.ensure_admin_account()
        self.assertIsNone(auth.authenticate_admin("admin", "admin"))
        self.assertIsNotNone(auth.authenticate_admin("admin", "new-password-123"))

    def test_wrong_current_password_preserves_password_and_session(self):
        token = auth.create_admin_session(1)
        self.assertFalse(auth.change_admin_password(1, "wrong", "new-password-123"))
        self.assertIsNotNone(auth.get_admin_session(token))
        self.assertIsNotNone(auth.authenticate_admin("admin", "admin"))
        with self.assertRaises(ValueError):
            auth.change_admin_password(1, "admin", "short")

    def test_hashes_use_distinct_salts_and_corrupted_hash_is_rejected(self):
        self.assertNotEqual(auth.hash_password("admin"), auth.hash_password("admin"))
        self.assertFalse(auth.verify_password("admin", "broken"))
        self.assertFalse(auth.verify_password("admin", "pbkdf2_sha256$9999999999$00$00"))

    def page(self):
        return AppTest.from_file(str(Path(__file__).resolve().parents[1] / "admin_panel.py"), default_timeout=15)

    def test_login_form_rejects_bad_password_and_accepts_database_credentials(self):
        with patch("requests.get", return_value=Mock(json=lambda: {"ok": False})):
            page = self.page().run()
            self.assertEqual(list(page.exception), [])
            self.assertEqual([field.label for field in page.text_input], ["Логин", "Пароль"])
            page.text_input(key="login_username").set_value("admin")
            page.text_input(key="login_password").set_value("wrong")
            next(button for button in page.button if button.label == "Войти").click().run()
            self.assertEqual(page.error[0].value, "Неверный логин или пароль")
            page.text_input(key="login_password").set_value("admin")
            next(button for button in page.button if button.label == "Войти").click().run()
            self.assertEqual(list(page.exception), [])
            self.assertEqual(page.sidebar.radio[0].label, "Навигация:")
            token = page.query_params["admin_session"][0]
            self.assertIsNotNone(auth.get_admin_session(token))
            next(button for button in page.button if "Выйти" in button.label).click().run()
            self.assertIsNone(auth.get_admin_session(token))
            self.assertEqual([field.label for field in page.text_input], ["Логин", "Пароль"])

    def test_session_state_flags_cannot_bypass_login(self):
        page = self.page()
        page.session_state["admin_authenticated"] = True
        page.session_state["admin_auth_until"] = (datetime.utcnow() + timedelta(days=100)).timestamp()
        page.run()
        self.assertEqual([field.label for field in page.text_input], ["Логин", "Пароль"])
        self.assertEqual(len(page.sidebar.radio), 0)

    def test_profile_password_change_keeps_current_session_and_revokes_other_sessions(self):
        other_token = auth.create_admin_session(1)
        with patch("requests.get", return_value=Mock(json=lambda: {"ok": False})):
            page = self.page()
            page.query_params["admin_session"] = auth.create_admin_session(1)
            page.run()
            page.sidebar.radio[0].set_value("👤 Профиль").run()
            for field, value in zip(page.text_input, ("admin", "another-password-123", "another-password-123")):
                field.set_value(value)
            next(button for button in page.button if button.label == "Сохранить пароль").click().run()
            self.assertEqual(list(page.exception), [])
            self.assertIsNone(auth.get_admin_session(other_token))
            self.assertIsNotNone(auth.get_admin_session(page.query_params["admin_session"][0]))
            self.assertIsNotNone(auth.authenticate_admin("admin", "another-password-123"))


if __name__ == "__main__":
    unittest.main()
