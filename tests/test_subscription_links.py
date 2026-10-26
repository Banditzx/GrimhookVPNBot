import asyncio
from datetime import datetime, timedelta
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from test_activation_codes import handlers
from config import Config, config
from functions import XUIAPI, generate_subscription_url


class SubscriptionURLTests(unittest.TestCase):
    def test_builds_individual_subscription_urls(self):
        with patch.object(config, "XUI_SUBSCRIPTION_BASE_URL", "https://vpn.example:2096/sub"):
            self.assertEqual(generate_subscription_url({"sub_id": "user-one"}), "https://vpn.example:2096/sub/user-one")
            self.assertEqual(generate_subscription_url({"sub_id": "user-two"}), "https://vpn.example:2096/sub/user-two")

    def test_subscription_requires_configured_base_and_client_sub_id(self):
        with patch.object(config, "XUI_SUBSCRIPTION_BASE_URL", "https://vpn.example/sub"):
            for profile in ({}, {"sub_id": ""}, {"sub_id": None}, {"sub_id": "  "}, {"sub_id": 12}):
                self.assertIsNone(generate_subscription_url(profile))
        with patch.object(config, "XUI_SUBSCRIPTION_BASE_URL", ""):
            self.assertIsNone(generate_subscription_url({"sub_id": "user-one"}))

    def test_sub_id_cannot_change_url_host_or_path(self):
        with patch.object(config, "XUI_SUBSCRIPTION_BASE_URL", "https://vpn.example/sub"):
            self.assertEqual(
                generate_subscription_url({"sub_id": "a/b?x=1#test"}),
                "https://vpn.example/sub/a%2Fb%3Fx%3D1%23test",
            )

    def test_config_normalizes_base_and_rejects_non_subscription_urls(self):
        self.assertEqual(Config(XUI_SUBSCRIPTION_BASE_URL=" https://vpn.example:2096/sub/ ").XUI_SUBSCRIPTION_BASE_URL, "https://vpn.example:2096/sub")
        self.assertEqual(Config(XUI_SUBSCRIPTION_BASE_URL="").XUI_SUBSCRIPTION_BASE_URL, "")
        for url in ("vpn.example/sub", "file:///sub", "https://user:pass@vpn.example/sub", "https://vpn.example/sub?id=x", "https://vpn.example/sub#id"):
            with self.assertRaises(ValidationError):
                Config(XUI_SUBSCRIPTION_BASE_URL=url)

    def test_new_client_keeps_actual_sub_id_returned_by_panel(self):
        async def check():
            api = XUIAPI()
            inbound = {"protocol": "trojan", "port": 443, "remark": "Test", "streamSettings": {}}
            with patch.object(api, "login", AsyncMock(return_value=True)), \
                 patch.object(api, "get_inbound", AsyncMock(return_value=inbound)), \
                 patch.object(api, "_panel_request", AsyncMock(return_value=True)), \
                 patch.object(api, "get_client_by_email", AsyncMock(return_value={"password": "secret", "subId": "actual-panel-sub-id"})), \
                 patch.object(api, "get_client_links", AsyncMock(return_value=["trojan://test@example:443"])):
                result = await api.create_vless_profile(1, datetime.utcnow() + timedelta(days=30))
                self.assertEqual(result["sub_id"], "actual-panel-sub-id")
                result = await api.create_static_client("test")
                self.assertEqual(result["sub_id"], "actual-panel-sub-id")
        asyncio.run(check())


class SubscriptionConnectTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(patch.object(config, "INBOUND_IDS", [1]))
        self.user = SimpleNamespace(
            telegram_id=1, is_admin=False, subscription_end=datetime.utcnow() + timedelta(days=10),
            vless_profile_data=json.dumps({"email": "user_1_test", "connection_url": "vless://secret@example:443", "sub_id": "stale-id"}),
        )
        self.callback = SimpleNamespace(
            from_user=SimpleNamespace(id=1), answer=AsyncMock(),
            message=SimpleNamespace(answer=AsyncMock(), edit_text=AsyncMock()),
        )
        self.enterContext(patch.object(config, "XUI_SUBSCRIPTION_BASE_URL", "https://vpn.example:2096/sub"))
        self.enterContext(patch.object(handlers, "get_user", AsyncMock(return_value=self.user)))
        self.enterContext(patch.object(handlers, "has_payment_records", AsyncMock(return_value=True)))
        self.enterContext(patch.object(handlers, "has_redeemed_codes", AsyncMock(return_value=False)))
        self.panel = self.enterContext(patch.object(handlers, "get_client_by_email", AsyncMock(return_value={"subId": "fresh-user-one"})))
        self.direct_links = self.enterContext(patch.object(handlers, "get_client_links_by_email", AsyncMock(return_value=["vless://secret@example:443"])))
        self.save = self.enterContext(patch.object(handlers, "save_user_profile_data", AsyncMock(return_value=self.user)))
        self.mark_deleted = self.enterContext(patch.object(handlers, "mark_user_profile_deleted", AsyncMock(return_value=True)))
        self.create = self.enterContext(patch.object(handlers, "create_vless_profile", AsyncMock(return_value={
            "email": "user_1_new", "sub_id": "new-user-one", "connection_url": "vless://new@example:443",
        })))

    async def test_existing_profile_uses_fresh_sub_id_and_subscription_button(self):
        await handlers.connect_profile(self.callback, AsyncMock())
        message = self.callback.message.edit_text.await_args
        self.assertIn("https://vpn.example:2096/sub/fresh-user-one", message.args[0])
        self.assertNotIn("vless://", message.args[0])
        self.assertNotIn("stale-id", message.args[0])
        button = message.kwargs["reply_markup"].inline_keyboard[0][0]
        self.assertEqual(button.text, "Открыть подписку")
        self.assertEqual(button.url, "https://vpn.example:2096/sub/fresh-user-one")
        self.assertTrue(message.kwargs["link_preview_options"].is_disabled)
        self.assertEqual(self.save.await_args.args[1]["sub_id"], "fresh-user-one")
        self.create.assert_not_awaited()
        self.direct_links.assert_not_awaited()

    async def test_legacy_profile_without_stored_sub_id_is_upgraded(self):
        self.user.vless_profile_data = json.dumps({"email": "user_1_test"})
        await handlers.connect_profile(self.callback, AsyncMock())
        self.assertIn("/sub/fresh-user-one", self.callback.message.edit_text.await_args.args[0])

    async def test_new_profile_uses_its_own_subscription_id(self):
        self.user.vless_profile_data = None
        await handlers.connect_profile(self.callback, AsyncMock())
        self.assertIn("/sub/new-user-one", self.callback.message.edit_text.await_args.args[0])
        self.create.assert_awaited_once_with(1, self.user.subscription_end)
        self.direct_links.assert_not_awaited()

    async def test_missing_panel_client_is_recreated_with_new_subscription_link(self):
        self.panel.return_value = False
        await handlers.connect_profile(self.callback, AsyncMock())
        self.mark_deleted.assert_awaited_once_with(1)
        self.assertIn("/sub/new-user-one", self.callback.message.edit_text.await_args.args[0])
        self.assertNotIn("stale-id", self.callback.message.edit_text.await_args.args[0])

    async def test_missing_sub_id_does_not_expose_stale_or_direct_link(self):
        self.panel.return_value = {"subId": ""}
        await handlers.connect_profile(self.callback, AsyncMock())
        self.callback.message.edit_text.assert_not_awaited()
        self.assertIn("отсутствует Sub ID", self.callback.message.answer.await_args.args[0])
        self.direct_links.assert_not_awaited()

    async def test_panel_failure_does_not_recreate_existing_profile(self):
        self.panel.return_value = None
        await handlers.connect_profile(self.callback, AsyncMock())
        self.create.assert_not_awaited()
        self.callback.message.edit_text.assert_not_awaited()

    async def test_other_client_receives_different_subscription_link(self):
        self.user.telegram_id = 2
        self.callback.from_user.id = 2
        self.user.vless_profile_data = json.dumps({"email": "user_2_test"})
        self.panel.return_value = {"subId": "user-two"}
        await handlers.connect_profile(self.callback, AsyncMock())
        self.panel.assert_awaited_once_with("user_2_test")
        self.assertIn("/sub/user-two", self.callback.message.edit_text.await_args.args[0])
        self.assertNotIn("fresh-user-one", self.callback.message.edit_text.await_args.args[0])

    async def test_empty_base_preserves_direct_connection_mode(self):
        with patch.object(config, "XUI_SUBSCRIPTION_BASE_URL", ""):
            await handlers.connect_profile(self.callback, AsyncMock())
        self.assertIn("vless://secret@example:443", self.callback.message.edit_text.await_args.args[0])
        markup = self.callback.message.edit_text.await_args.kwargs["reply_markup"]
        self.assertFalse(any(button.text == "Открыть подписку" for row in markup.inline_keyboard for button in row))
        self.direct_links.assert_awaited_once_with("user_1_test")


if __name__ == "__main__":
    unittest.main()
