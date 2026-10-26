import asyncio
from datetime import datetime, timedelta
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from test_activation_codes import handlers
from config import Config, config
from functions import XUIAPI, get_global_stats


class MultipleInboundConfigTests(unittest.TestCase):
    def test_parses_ordered_unique_positive_ids(self):
        value = Config(INBOUND_IDS=" 2,3,4,2 ")
        self.assertEqual(value.INBOUND_IDS, [2, 3, 4])
        self.assertEqual(Config(INBOUND_IDS=[4, 2]).INBOUND_IDS, [4, 2])

    def test_single_inbound_uses_the_same_array_setting(self):
        self.assertEqual(Config(INBOUND_IDS="2").INBOUND_IDS, [2])
        self.assertEqual(Config(INBOUND_IDS=[2]).INBOUND_IDS, [2])

    def test_default_is_a_single_inbound_array(self):
        self.assertEqual(Config().INBOUND_IDS, [1])

    def test_invalid_lists_are_rejected_before_provisioning(self):
        for value in ("", "  ", [], "2,,4", "0,2", "-1,2", "2,three", "2.5,3", [True], [2, 0], None, 2):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Config(INBOUND_IDS=value)


class MultipleInboundAPITests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(patch.object(config, "INBOUND_IDS", [2, 3, 4]))
        self.api = XUIAPI()
        self.login = self.enterContext(patch.object(self.api, "login", AsyncMock(return_value=True)))
        self.request = self.enterContext(patch.object(self.api, "_panel_request", AsyncMock(return_value=True)))
        self.client = self.enterContext(patch.object(self.api, "get_client_by_email", AsyncMock(return_value={
            "email": "user_1_test", "uuid": "user-uuid", "password": "user-password", "subId": "shared-sub-id",
            "inboundIds": [2, 3, 4],
        })))
        inbounds = {
            2: {"id": 2, "protocol": "trojan", "port": 443, "remark": "Trojan", "enable": True},
            3: {"id": 3, "protocol": "vless", "port": 8443, "remark": "VLESS", "enable": True},
            4: {"id": 4, "protocol": "hysteria", "port": 4443, "remark": "Hysteria", "enable": True},
        }
        self.inbound_data = inbounds
        self.inbound = self.enterContext(patch.object(self.api, "get_inbound", AsyncMock(side_effect=lambda key: inbounds.get(key))))
        self.links = self.enterContext(patch.object(self.api, "get_client_links", AsyncMock(return_value=["trojan://secret@example:443"])))

    async def test_creates_one_client_on_all_three_inbounds(self):
        end = datetime.utcnow() + timedelta(days=30)
        result = await self.api.create_vless_profile(1, end)
        self.assertEqual([call.args[0] for call in self.inbound.await_args_list], [2, 3, 4])
        self.request.assert_awaited_once()
        request = self.request.await_args
        self.assertEqual(request.args, ("POST", "/panel/api/clients/add"))
        self.assertEqual(request.kwargs["json"]["inboundIds"], [2, 3, 4])
        self.assertEqual(request.kwargs["json"]["client"]["expiryTime"], self.api._datetime_to_ms(end))
        self.assertEqual(result["inbound_ids"], [2, 3, 4])
        self.assertEqual(result["sub_id"], "shared-sub-id")
        self.assertEqual(result["client_id"], "user-uuid")

    async def test_single_inbound_creation_sends_a_one_element_array(self):
        with patch.object(config, "INBOUND_IDS", [2]):
            self.client.return_value["inboundIds"] = [2]
            result = await self.api.create_vless_profile(1, datetime.utcnow() + timedelta(days=1))
        self.request.assert_awaited_once()
        self.assertEqual(self.request.await_args.kwargs["json"]["inboundIds"], [2])
        self.inbound.assert_awaited_once_with(2)
        self.assertEqual(result["inbound_ids"], [2])

    async def test_global_stats_use_first_configured_inbound(self):
        with patch("functions.XUIAPI", return_value=self.api):
            result = await get_global_stats()
        self.inbound.assert_awaited_once_with(2)
        self.assertEqual(result, {"upload": 0, "download": 0, "total": 0})

    async def test_missing_inbound_prevents_any_creation(self):
        del self.inbound_data[4]
        self.assertIsNone(await self.api.create_vless_profile(1, datetime.utcnow() + timedelta(days=1)))
        self.request.assert_not_awaited()

    async def test_disabled_inbound_prevents_any_creation(self):
        self.inbound_data[3]["enable"] = False
        self.assertIsNone(await self.api.create_vless_profile(1, datetime.utcnow() + timedelta(days=1)))
        self.request.assert_not_awaited()

    async def test_static_client_uses_same_inbound_list(self):
        result = await self.api.create_static_client("test")
        self.assertEqual(self.request.await_args.kwargs["json"]["inboundIds"], [2, 3, 4])
        self.assertEqual(self.request.await_args.kwargs["json"]["client"]["expiryTime"], 0)
        self.assertEqual(result["sub_id"], "shared-sub-id")

    async def test_add_partial_failure_preserves_created_identity(self):
        self.request.return_value = False
        self.client.return_value = {"email": "user_1_test", "subId": "same-sub-id", "inboundIds": [2], "password": "secret"}
        result = await self.api.create_vless_profile(1, datetime.utcnow() + timedelta(days=1))
        self.assertIsNotNone(result)
        self.assertEqual(result["inbound_ids"], [2])
        self.assertEqual(result["sub_id"], "same-sub-id")

    async def test_add_total_failure_returns_no_profile(self):
        self.request.return_value = False
        self.client.return_value = False
        self.assertIsNone(await self.api.create_vless_profile(1, datetime.utcnow() + timedelta(days=1)))

    async def test_existing_client_gets_only_missing_inbounds(self):
        initial = {"email": "user_1_test", "subId": "same-id", "inboundIds": [2, 8]}
        self.client.return_value = {**initial, "inboundIds": [2, 8, 3, 4]}
        result = await self.api.ensure_client_inbounds("user_1_test", initial)
        self.request.assert_awaited_once_with("POST", "/panel/api/clients/user_1_test/attach", json={"inboundIds": [3, 4]})
        self.assertEqual(result["subId"], "same-id")
        self.assertIn(8, result["inboundIds"])

    async def test_fully_attached_client_does_not_trigger_writes(self):
        initial = self.client.return_value
        result = await self.api.ensure_client_inbounds("user_1_test", initial)
        self.assertIs(result, initial)
        self.request.assert_not_awaited()
        self.client.assert_not_awaited()

    async def test_unmanaged_clients_are_never_attached(self):
        self.assertIsNone(await self.api.ensure_client_inbounds("manual", {"inboundIds": [2]}))
        self.request.assert_not_awaited()

    async def test_attachment_is_verified_and_can_be_retried(self):
        initial = {"subId": "same-id", "inboundIds": [2]}
        self.client.return_value = {"subId": "same-id", "inboundIds": [2, 3]}
        self.assertIsNone(await self.api.ensure_client_inbounds("user_1_test", initial))
        partial = self.client.return_value
        self.client.return_value = {"subId": "same-id", "inboundIds": [2, 3, 4]}
        self.request.reset_mock()
        self.assertIsNotNone(await self.api.ensure_client_inbounds("user_1_test", partial))
        self.request.assert_awaited_once_with("POST", "/panel/api/clients/user_1_test/attach", json={"inboundIds": [4]})

    async def test_nested_api_response_is_normalized_for_sub_id_and_expiry(self):
        with patch.object(self.api, "get_client_by_email", wraps=XUIAPI.get_client_by_email.__get__(self.api, XUIAPI)):
            self.request.return_value = {
                "client": {"id": 10, "uuid": "user-uuid", "subId": "same-id", "expiryTime": 1234},
                "inboundIds": [2, 3, 4], "externalLinks": [], "usedTraffic": 0,
            }
            result = await self.api.get_client_by_email("user_1_test")
            self.assertEqual(result["subId"], "same-id")
            self.assertEqual(result["inboundIds"], [2, 3, 4])
            self.assertNotIn("client", result)

    async def test_expiry_update_keeps_credentials_and_updates_single_client(self):
        end = datetime.utcnow() + timedelta(days=90)
        initial = {"id": 123, "uuid": "same-uuid", "password": "same-password", "subId": "same-sub-id", "expiryTime": 1, "inboundIds": [2, 3, 4]}
        self.client.side_effect = [initial, {**initial, "expiryTime": self.api._datetime_to_ms(end)}]
        self.assertTrue(await self.api.update_client_expiry("user_1_test", end))
        self.request.assert_awaited_once()
        payload = self.request.await_args.kwargs["json"]
        self.assertEqual(self.request.await_args.args, ("POST", "/panel/api/clients/update/user_1_test"))
        self.assertEqual(payload["id"], "same-uuid")
        self.assertEqual(payload["password"], "same-password")
        self.assertEqual(payload["subId"], "same-sub-id")
        self.assertNotIn("inboundIds", payload)
        self.assertNotIn("uuid", payload)

    async def test_nested_api_client_can_be_renewed_without_sending_database_id(self):
        end = datetime.utcnow() + timedelta(days=30)
        before = {"client": {"id": 123, "uuid": "same-uuid", "subId": "same-id", "expiryTime": 1}, "inboundIds": [2, 3, 4]}
        after = {**before, "client": {**before["client"], "expiryTime": self.api._datetime_to_ms(end)}}
        with patch.object(self.api, "get_client_by_email", wraps=XUIAPI.get_client_by_email.__get__(self.api, XUIAPI)):
            self.request.side_effect = [before, True, after]
            self.assertTrue(await self.api.update_client_expiry("user_1_test", end))
            update = self.request.await_args_list[1]
            self.assertEqual(update.args, ("POST", "/panel/api/clients/update/user_1_test"))
            self.assertEqual(update.kwargs["json"]["id"], "same-uuid")
            self.assertNotIn("uuid", update.kwargs["json"])
            self.assertNotIn("client", update.kwargs["json"])

    async def test_legacy_string_uuid_in_id_is_preserved(self):
        end = datetime.utcnow() + timedelta(days=30)
        initial = {"id": "legacy-uuid", "subId": "same-id", "expiryTime": 1}
        self.client.side_effect = [initial, {**initial, "expiryTime": self.api._datetime_to_ms(end)}]
        self.assertTrue(await self.api.update_client_expiry("user_1_test", end))
        self.assertEqual(self.request.await_args.kwargs["json"]["id"], "legacy-uuid")

    async def test_record_fields_are_converted_to_protocol_client_types(self):
        end = datetime.utcnow() + timedelta(days=30)
        initial = {
            "id": 123, "uuid": "same-uuid", "subId": "same-id", "expiryTime": 1,
            "allowedIPs": "10.0.0.1/32, 2001:db8::1/128", "createdAt": 100,
            "updatedAt": 200, "reverse": '{"tag":"keep-reverse"}',
        }
        self.client.side_effect = [initial, {**initial, "expiryTime": self.api._datetime_to_ms(end)}]
        self.assertTrue(await self.api.update_client_expiry("user_1_test", end))
        payload = self.request.await_args.kwargs["json"]
        self.assertEqual(payload["allowedIPs"], ["10.0.0.1/32", "2001:db8::1/128"])
        self.assertEqual(payload["created_at"], 100)
        self.assertGreater(payload["updated_at"], 200)
        self.assertEqual(payload["reverse"], {"tag": "keep-reverse"})

    async def test_empty_allowed_ips_becomes_array_without_erasing_secrets(self):
        end = datetime.utcnow() + timedelta(days=30)
        initial = {"id": 123, "uuid": "", "subId": "same-id", "expiryTime": 1, "allowedIPs": "", "auth": "same-auth", "secret": "same-secret", "password": "same-password"}
        self.client.side_effect = [initial, {**initial, "expiryTime": self.api._datetime_to_ms(end)}]
        self.assertTrue(await self.api.update_client_expiry("user_1_test", end))
        payload = self.request.await_args.kwargs["json"]
        self.assertEqual(payload["allowedIPs"], [])
        self.assertEqual(payload["auth"], "same-auth")
        self.assertEqual(payload["secret"], "same-secret")
        self.assertEqual(payload["password"], "same-password")
        self.assertNotIn("id", payload)


class MultipleInboundConnectTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(patch.object(config, "INBOUND_IDS", [2, 3, 4]))
        self.enterContext(patch.object(config, "XUI_SUBSCRIPTION_BASE_URL", "https://vpn.example/sub"))
        self.user = SimpleNamespace(
            telegram_id=1, is_admin=False, subscription_end=datetime.utcnow() + timedelta(days=30),
            vless_profile_data=json.dumps({"email": "user_1_test", "sub_id": "same-id"}),
        )
        self.callback = SimpleNamespace(from_user=SimpleNamespace(id=1), answer=AsyncMock(), message=SimpleNamespace(answer=AsyncMock(), edit_text=AsyncMock()))
        self.enterContext(patch.object(handlers, "get_user", AsyncMock(return_value=self.user)))
        self.enterContext(patch.object(handlers, "has_payment_records", AsyncMock(return_value=True)))
        self.enterContext(patch.object(handlers, "has_redeemed_codes", AsyncMock(return_value=False)))
        self.enterContext(patch.object(handlers, "get_client_by_email", AsyncMock(return_value={"subId": "same-id", "inboundIds": [2]})))
        self.attach = self.enterContext(patch.object(handlers, "ensure_client_inbounds_by_email", AsyncMock(return_value={"subId": "same-id", "inboundIds": [2, 3, 4]})))
        self.save = self.enterContext(patch.object(handlers, "save_user_profile_data", AsyncMock(return_value=self.user)))
        self.create = self.enterContext(patch.object(handlers, "create_vless_profile", AsyncMock()))

    async def test_existing_profile_keeps_same_subscription_url(self):
        await handlers.connect_profile(self.callback, AsyncMock())
        self.attach.assert_awaited_once()
        self.assertIn("https://vpn.example/sub/same-id", self.callback.message.edit_text.await_args.args[0])
        self.assertEqual(self.save.await_args.args[1]["inbound_ids"], [2, 3, 4])
        self.create.assert_not_awaited()

    async def test_attachment_failure_does_not_replace_existing_profile(self):
        self.attach.return_value = None
        await handlers.connect_profile(self.callback, AsyncMock())
        self.callback.message.edit_text.assert_not_awaited()
        self.create.assert_not_awaited()
        self.assertIn("Подписка сохранена", self.callback.message.answer.await_args.args[0])

    async def test_new_partially_attached_client_is_saved_for_retry(self):
        self.user.vless_profile_data = None
        partial = {"email": "user_1_new", "sub_id": "new-id", "inbound_ids": [2]}
        self.create.return_value = partial
        self.attach.return_value = None
        await handlers.connect_profile(self.callback, AsyncMock())
        self.save.assert_awaited_once_with(1, partial)
        self.assertIn("Подписка сохранена", self.callback.message.answer.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
