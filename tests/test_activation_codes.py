import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
TEST_STORAGE = tempfile.TemporaryDirectory(prefix="grimhook-codes-test-")
os.environ["BOT_DATABASE_PATH"] = str(Path(TEST_STORAGE.name) / "bootstrap.db")

import database as db
import handlers


class ActivationCodeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=TEST_STORAGE.name)
        self.old_engine, self.old_session = db.engine, db.Session
        db.engine = create_engine(f"sqlite:///{self.folder.name}/users.db")
        db.Session = sessionmaker(bind=db.engine)
        db.Base.metadata.create_all(db.engine)
        with db.Session.begin() as session:
            session.add_all([db.User(telegram_id=1), db.User(telegram_id=2)])

    def tearDown(self):
        db.engine.dispose()
        db.engine, db.Session = self.old_engine, self.old_session
        self.folder.cleanup()

    def user(self, telegram_id=1):
        return asyncio.run(db.get_user(telegram_id))

    def record(self):
        with db.Session() as session:
            return session.query(db.ActivationCode).first()

    def test_new_and_expired_subscriptions_start_from_activation(self):
        for user_id in (1, 2):
            if user_id == 2:
                with db.Session.begin() as session:
                    session.query(db.User).filter_by(telegram_id=2).update({
                        db.User.subscription_end: datetime.utcnow() - timedelta(days=15),
                    })
            before = datetime.utcnow()
            result = db.redeem_activation_code(user_id, db.create_activation_codes(3)[0])
            self.assertEqual(result["status"], "activated")
            self.assertGreaterEqual(result["subscription_end"], before + timedelta(days=90))
            self.assertLessEqual(result["subscription_end"], datetime.utcnow() + timedelta(days=90))

    def test_active_trial_is_extended_without_losing_remaining_days(self):
        end = datetime.utcnow() + timedelta(hours=20)
        with db.Session.begin() as session:
            session.query(db.User).filter_by(telegram_id=1).update({
                db.User.subscription_end: end, db.User.notified: True,
            })
        result = db.redeem_activation_code(1, db.create_activation_codes(12)[0])
        self.assertEqual(result["subscription_end"], end + timedelta(days=360))
        self.assertFalse(self.user().notified)

    def test_all_durations_one_to_twelve(self):
        for months in range(1, 13):
            with self.subTest(months=months):
                before = self.user().subscription_end or datetime.utcnow()
                result = db.redeem_activation_code(1, db.create_activation_codes(months)[0])
                self.assertEqual(result["months"], months)
                self.assertGreaterEqual(result["subscription_end"], before + timedelta(days=months * 30))

    def test_code_is_single_use_across_users(self):
        code = db.create_activation_codes(1)[0]
        self.assertEqual(db.redeem_activation_code(1, code)["status"], "activated")
        end = self.user().subscription_end
        for user_id in (1, 2):
            self.assertEqual(db.redeem_activation_code(user_id, code)["status"], "used")
        self.assertEqual(self.user().subscription_end, end)
        self.assertIsNone(self.user(2).subscription_end)
        self.assertEqual(self.record().used_by, 1)
        self.assertEqual(self.record().subscription_end, end)

    def test_case_spaces_and_hyphens_are_accepted(self):
        code = db.create_activation_codes(1)[0]
        self.assertEqual(db.redeem_activation_code(1, " \n" + code.lower().replace("-", " ") + "\n")["status"], "activated")

    def test_invalid_and_missing_codes_do_not_change_subscription(self):
        for value in (None, "", "wrong", "' OR 1=1 --", "x" * 101, "GVPN-" + "A" * 20):
            self.assertEqual(db.redeem_activation_code(1, value)["status"], "invalid")
        self.assertIsNone(self.user().subscription_end)

    def test_user_must_exist_and_failed_attempt_does_not_consume_key(self):
        code = db.create_activation_codes(1)[0]
        self.assertEqual(db.redeem_activation_code(999, code)["status"], "user_missing")
        self.assertIsNone(self.record().used_at)
        self.assertEqual(db.redeem_activation_code(1, code)["status"], "activated")

    def test_revocation_only_allows_unused_keys(self):
        code = db.create_activation_codes(1)[0]
        key_id = self.record().id
        self.assertTrue(db.revoke_activation_code(key_id))
        self.assertFalse(db.revoke_activation_code(key_id))
        self.assertEqual(db.redeem_activation_code(1, code)["status"], "revoked")
        used_code = db.create_activation_codes(1)[0]
        db.redeem_activation_code(1, used_code)
        with db.Session() as session:
            used_id = session.query(db.ActivationCode).filter_by(used_by=1).one().id
        self.assertFalse(db.revoke_activation_code(used_id))

    def test_database_never_stores_full_keys(self):
        codes = db.create_activation_codes(12, 100, "Продажа партии")
        self.assertEqual(len(set(codes)), 100)
        with db.engine.connect() as connection:
            dump = str(connection.execute(db.text("SELECT * FROM activation_codes")).fetchall())
        for code in codes:
            self.assertNotIn(code, dump)
            self.assertNotIn(code.replace("-", ""), dump)

    def test_generation_rejects_out_of_range_inputs(self):
        for months, quantity in ((0, 1), (13, 1), (1.5, 1), (True, 1), (1, 0), (1, 101)):
            with self.assertRaises(ValueError):
                db.create_activation_codes(months, quantity)

    def test_concurrent_redemption_grants_only_one_subscription(self):
        code = db.create_activation_codes(1)[0]
        barrier = threading.Barrier(8)

        def redeem(index):
            barrier.wait()
            return db.redeem_activation_code(index % 2 + 1, code)["status"]

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(redeem, range(8)))
        self.assertEqual(results.count("activated"), 1)
        self.assertEqual(results.count("used"), 7)
        self.assertEqual(sum(self.user(i).subscription_end is not None for i in (1, 2)), 1)

    def test_concurrent_different_keys_stack_for_same_user(self):
        codes = db.create_activation_codes(1, 2)
        initial_end = datetime.utcnow() + timedelta(days=1)
        with db.Session.begin() as session:
            session.query(db.User).filter_by(telegram_id=1).update({db.User.subscription_end: initial_end})
        barrier = threading.Barrier(2)

        def redeem(code):
            barrier.wait()
            return db.redeem_activation_code(1, code)["status"]

        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(list(executor.map(redeem, codes)), ["activated", "activated"])
        self.assertEqual(self.user().subscription_end, initial_end + timedelta(days=60))

    def test_revoke_and_redeem_cannot_both_succeed(self):
        code = db.create_activation_codes(1)[0]
        code_id = self.record().id
        barrier = threading.Barrier(2)

        def revoke():
            barrier.wait()
            return db.revoke_activation_code(code_id)

        def redeem():
            barrier.wait()
            return db.redeem_activation_code(1, code)["status"]

        with ThreadPoolExecutor(max_workers=2) as executor:
            revoked = executor.submit(revoke)
            redeemed = executor.submit(redeem)
            self.assertIn((revoked.result(), redeemed.result()), [(True, "revoked"), (False, "activated")])

    def test_database_failure_rolls_back_key_and_subscription_together(self):
        code = db.create_activation_codes(1)[0]

        def fail_flush(session, context, instances):
            if session.dirty:
                raise RuntimeError("simulated write failure")

        event.listen(db.Session.class_, "before_flush", fail_flush)
        try:
            with self.assertRaises(RuntimeError):
                db.redeem_activation_code(1, code)
        finally:
            event.remove(db.Session.class_, "before_flush", fail_flush)
        self.assertIsNone(self.user().subscription_end)
        self.assertIsNone(self.record().used_at)
        self.assertEqual(db.redeem_activation_code(1, code)["status"], "activated")

    def test_restart_keeps_activated_subscription_without_vpn_profile(self):
        db.redeem_activation_code(1, db.create_activation_codes(12)[0])
        end = self.user().subscription_end
        asyncio.run(db.init_db())
        asyncio.run(db.init_db())
        self.assertEqual(self.user().subscription_end, end)
        self.assertTrue(asyncio.run(db.has_redeemed_codes(1)))

    def test_restart_keeps_admin_twelve_month_subscription(self):
        import app
        db.redeem_activation_code(1, db.create_activation_codes(12)[0])
        end = self.user().subscription_end
        with patch.object(app, "Session", db.Session), patch.object(app.config, "ADMINS", [1]):
            asyncio.run(app.update_admins_status())
        self.assertEqual(self.user().subscription_end, end)
        self.assertTrue(self.user().is_admin)

    def test_bot_activation_updates_existing_vpn_profile(self):
        profile = '{"email": "user_1_test"}'
        with db.Session.begin() as session:
            session.query(db.User).filter_by(telegram_id=1).update({db.User.vless_profile_data: profile})
        message = SimpleNamespace(text=db.create_activation_codes(2)[0], from_user=SimpleNamespace(id=1), answer=AsyncMock())
        state, bot = AsyncMock(), AsyncMock()
        with patch.object(handlers, "show_menu", AsyncMock()), \
             patch.object(handlers, "get_client_by_email", AsyncMock(return_value={"email": "user_1_test"})), \
             patch.object(handlers, "sync_vpn_expiry", AsyncMock(return_value=True)) as sync:
            asyncio.run(handlers.activation_code_submit(message, state, bot))
        sync.assert_awaited_once_with(profile, self.user().subscription_end)
        state.clear.assert_awaited_once()

    def test_panel_failure_does_not_lose_or_duplicate_redeemed_subscription(self):
        with db.Session.begin() as session:
            session.query(db.User).filter_by(telegram_id=1).update({db.User.vless_profile_data: '{"email": "user_1_test"}'})
        code = db.create_activation_codes(1)[0]
        message = SimpleNamespace(text=code, from_user=SimpleNamespace(id=1), answer=AsyncMock())
        with patch.object(handlers, "show_menu", AsyncMock()), \
             patch.object(handlers, "get_client_by_email", AsyncMock(return_value=None)):
            asyncio.run(handlers.activation_code_submit(message, AsyncMock(), AsyncMock()))
        end = self.user().subscription_end
        self.assertIsNotNone(end)
        self.assertEqual(db.redeem_activation_code(1, code)["status"], "used")
        self.assertEqual(self.user().subscription_end, end)
        self.assertTrue(any("сохранена" in call.args[0] for call in message.answer.await_args_list))

    def test_missing_vpn_profile_is_marked_for_recreation_after_activation(self):
        with db.Session.begin() as session:
            session.query(db.User).filter_by(telegram_id=1).update({db.User.vless_profile_data: '{"email": "user_1_test"}'})
        message = SimpleNamespace(text=db.create_activation_codes(1)[0], from_user=SimpleNamespace(id=1), answer=AsyncMock())
        with patch.object(handlers, "show_menu", AsyncMock()), \
             patch.object(handlers, "get_client_by_email", AsyncMock(return_value=False)), \
             patch.object(handlers, "sync_vpn_expiry", AsyncMock()) as sync:
            asyncio.run(handlers.activation_code_submit(message, AsyncMock(), AsyncMock()))
        self.assertIn('"xui_deleted": true', self.user().vless_profile_data)
        sync.assert_not_awaited()

    def test_expired_code_subscription_cannot_start_another_free_trial(self):
        db.redeem_activation_code(1, db.create_activation_codes(1)[0])
        with db.Session.begin() as session:
            session.query(db.User).filter_by(telegram_id=1).update({db.User.subscription_end: datetime.utcnow() - timedelta(days=1)})
        callback = SimpleNamespace(from_user=SimpleNamespace(id=1), answer=AsyncMock(), message=SimpleNamespace(message_id=10))
        with patch.object(handlers, "show_menu", AsyncMock()), \
             patch.object(handlers, "activate_trial_subscription", AsyncMock()) as trial:
            asyncio.run(handlers.connect_profile(callback, AsyncMock()))
        trial.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
