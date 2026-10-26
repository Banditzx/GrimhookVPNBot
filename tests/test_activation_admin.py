from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from streamlit.testing.v1 import AppTest

from test_activation_codes import db, TEST_STORAGE
from admin_auth import ensure_admin_account, authenticate_admin, create_admin_session


class ActivationAdminTests(unittest.TestCase):
    def test_generate_export_filter_activate_and_revoke(self):
        old_engine, old_session, old_path = db.engine, db.Session, db.DB_PATH
        with tempfile.TemporaryDirectory(dir=TEST_STORAGE.name) as folder:
            db.DB_PATH = Path(folder) / "admin.db"
            db.engine = create_engine(f"sqlite:///{db.DB_PATH}")
            db.Session = sessionmaker(bind=db.engine)
            db.Base.metadata.create_all(db.engine)
            with db.Session.begin() as session:
                session.add(db.User(telegram_id=1))
            try:
                ensure_admin_account()
                account = authenticate_admin("admin", "admin")
                with patch("requests.get", return_value=Mock(json=lambda: {"ok": False})):
                    page = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "admin_panel.py"), default_timeout=15)
                    page.query_params["admin_session"] = create_admin_session(account["id"])
                    page.run()
                    self.assertEqual(list(page.exception), [])
                    page.sidebar.radio[0].set_value("🔑 Коды активации").run()
                    self.assertEqual(list(page.exception), [])
                    next(w for w in page.selectbox if w.label == "Срок, месяцев").set_value(12)
                    page.number_input[0].set_value(3)
                    next(w for w in page.text_input if w.label == "Примечание к партии").set_value("Test batch")
                    next(b for b in page.button if b.label == "Создать коды").click().run()
                    self.assertEqual(list(page.exception), [])
                    batch = page.session_state["activation_code_batch"]
                    self.assertEqual(len(batch["codes"]), 3)
                    self.assertIn(",12,360", batch["csv"])
                    self.assertEqual(len(page.dataframe[0].value), 3)

                    code = batch["codes"][0]
                    self.assertEqual(db.redeem_activation_code(1, code)["status"], "activated")
                    page.run()
                    next(w for w in page.selectbox if w.label == "Статус").set_value("Активированные").run()
                    self.assertEqual(len(page.dataframe[0].value), 1)
                    self.assertEqual(page.dataframe[0].value.iloc[0]["Telegram ID"], "1")

                    next(w for w in page.selectbox if w.label == "Статус").set_value("Доступные").run()
                    self.assertEqual(len(page.dataframe[0].value), 2)
                    next(b for b in page.button if b.label == "Отозвать код").click().run()
                    self.assertEqual(list(page.exception), [])
                    self.assertEqual(len(page.dataframe[0].value), 1)
                    next(w for w in page.selectbox if w.label == "Статус").set_value("Отозванные").run()
                    self.assertEqual(len(page.dataframe[0].value), 1)
                    next(b for b in page.button if b.label == "Скрыть созданные ключи").click().run()
                    self.assertNotIn("activation_code_batch", page.session_state)
                    self.assertEqual(list(page.exception), [])
            finally:
                db.engine.dispose()
                db.engine, db.Session, db.DB_PATH = old_engine, old_session, old_path


if __name__ == "__main__":
    unittest.main()
