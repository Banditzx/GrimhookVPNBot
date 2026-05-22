import aiohttp
import json
import logging
import random
import string
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

from config import config


logger = logging.getLogger(__name__)


def is_managed_client_email(email: str | None) -> bool:
    return bool(email and email.startswith(config.XUI_MANAGED_CLIENT_PREFIX))


class XUIAPI:
    def __init__(self):
        self.session = None
        self.cookie_jar = None
        self.api_url = config.XUI_API_URL.rstrip("/")
        self.base_path = config.XUI_BASE_PATH.strip("/")

        if self.base_path:
            self.full_base_url = f"{self.api_url}/{self.base_path}"
        else:
            self.full_base_url = self.api_url

    async def login(self):
        """Bearer token authorization does not require password login."""
        if not self.session:
            self.cookie_jar = aiohttp.CookieJar(unsafe=True)
            self.session = aiohttp.ClientSession(
                cookie_jar=self.cookie_jar,
                trust_env=True,
            )
        if not config.XUI_TOKEN:
            logger.error("🛑 XUI_TOKEN is empty")
            return False
        return True

    async def _request(self, method, path, **kwargs):
        """Универсальный запрос к 3x-ui API с Bearer-авторизацией."""
        if not self.session:
            self.cookie_jar = aiohttp.CookieJar(unsafe=True)
            self.session = aiohttp.ClientSession(
                cookie_jar=self.cookie_jar,
                trust_env=True,
            )

        headers = kwargs.pop("headers", {})
        headers.update(
            {
                "Authorization": f"Bearer {config.XUI_TOKEN}",
                "Accept": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            }
        )
        kwargs["headers"] = headers

        prefixes = ["/api/inbounds", "/panel/api/inbounds", "/xui/API/inbounds"]

        for prefix in prefixes:
            url = f"{self.full_base_url.rstrip('/')}{prefix}{path}"
            try:
                if method == "GET":
                    async with self.session.get(url, ssl=False, **kwargs) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("success"):
                                return data.get("obj")
                        logger.debug(f"3x-ui GET {prefix}{path} failed with status {resp.status}")
                elif method == "POST":
                    async with self.session.post(url, ssl=False, **kwargs) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("success"):
                                return data.get("obj") if ("get" in path or "onlines" in path) else True
                        logger.debug(f"3x-ui POST {prefix}{path} failed with status {resp.status}")
            except Exception as e:
                logger.debug(f"3x-ui request failed for {prefix}{path}: {e}")
                continue
        return None

    async def get_inbound(self, inbound_id: int):
        return await self._request("GET", f"/get/{inbound_id}")

    async def update_inbound(self, inbound_id: int, data: dict):
        return await self._request("POST", f"/update/{inbound_id}", json=data)

    async def get_global_stats(self, inbound_id: int):
        inbound = await self.get_inbound(inbound_id)
        if not inbound:
            return {"upload": 0, "download": 0, "total": 0}
        return {
            "upload": inbound.get("up", 0),
            "download": inbound.get("down", 0),
            "total": inbound.get("total", 0),
        }

    async def get_client_by_email(self, email: str):
        if not is_managed_client_email(email):
            logger.warning(f"Ignored unmanaged 3x-ui client lookup: {email}")
            return False

        if not await self.login():
            return None

        inbound = await self.get_inbound(config.INBOUND_ID)
        if not inbound:
            return None

        try:
            settings = json.loads(inbound["settings"])
            clients = settings.get("clients", [])
            for client in clients:
                if client.get("email") == email:
                    return client
            return False
        except Exception as e:
            logger.exception(f"🛑 Get client by email error: {e}")
            return None

    def _build_update_data(self, inbound: dict, settings: dict) -> dict:
        return {
            "up": inbound["up"],
            "down": inbound["down"],
            "total": inbound["total"],
            "remark": inbound["remark"],
            "enable": inbound["enable"],
            "expiryTime": inbound["expiryTime"],
            "listen": inbound["listen"],
            "port": inbound["port"],
            "protocol": inbound["protocol"],
            "settings": json.dumps(settings, indent=2),
            "streamSettings": inbound["streamSettings"],
            "sniffing": inbound["sniffing"],
        }

    def _generate_sub_id(self, length: int = 16) -> str:
        alphabet = string.ascii_lowercase + string.digits
        return "".join(random.choice(alphabet) for _ in range(length))

    def _get_stream_settings(self, inbound: dict) -> dict:
        stream_settings = inbound.get("streamSettings") or {}
        if isinstance(stream_settings, str):
            try:
                return json.loads(stream_settings)
            except Exception:
                return {}
        return stream_settings

    def _build_client(self, protocol: str, email: str, expiry_time: int, telegram_id: str = "") -> dict:
        base_client = {
            "email": email,
            "limitIp": 0,
            "totalGB": 0,
            "expiryTime": expiry_time,
            "enable": True,
            "tgId": telegram_id,
            "subId": self._generate_sub_id(),
            "reset": 0,
        }

        if protocol == "trojan":
            now_ms = int(time.time() * 1000)
            return {
                **base_client,
                "password": uuid.uuid4().hex,
                "comment": "",
                "created_at": now_ms,
                "updated_at": now_ms,
            }

        return {
            **base_client,
            "id": str(uuid.uuid4()),
            "flow": "",
            "fingerprint": config.REALITY_FINGERPRINT,
            "publicKey": config.REALITY_PUBLIC_KEY,
            "shortId": config.REALITY_SHORT_ID.split(",")[0].strip(),
            "spiderX": config.REALITY_SPIDER_X,
        }

    def _datetime_to_ms(self, value: datetime) -> int:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp() * 1000)

    async def create_vless_profile(self, telegram_id: int, subscription_end: datetime | None = None):
        if not subscription_end or subscription_end <= datetime.utcnow():
            logger.warning(f"Refused to create VPN profile for {telegram_id}: subscription is expired")
            return None

        if not await self.login():
            return None

        inbound = await self.get_inbound(config.INBOUND_ID)
        if not inbound:
            logger.error(f"🛑 Inbound ID {config.INBOUND_ID} не найден в панели")
            return None

        try:
            settings = json.loads(inbound["settings"])
            clients = settings.get("clients", [])

            protocol = inbound.get("protocol", "vless")
            stream_settings = self._get_stream_settings(inbound)
            email = f"user_{telegram_id}_{random.randint(1000, 9999)}"
            expire_at = self._datetime_to_ms(subscription_end)
            new_client = self._build_client(protocol, email, expire_at, str(telegram_id))

            clients.append(new_client)
            settings["clients"] = clients

            if await self.update_inbound(config.INBOUND_ID, self._build_update_data(inbound, settings)):
                return {
                    "client_id": new_client.get("id") or new_client.get("password"),
                    "password": new_client.get("password"),
                    "email": email,
                    "port": inbound["port"],
                    "protocol": protocol,
                    "network": stream_settings.get("network", "tcp"),
                    "security": stream_settings.get("security", "reality" if protocol == "vless" else "none"),
                    "remark": inbound["remark"],
                }
            return None
        except Exception as e:
            logger.exception(f"🛑 Create profile error: {e}")
            return None

    async def create_static_client(self, profile_name: str):
        if not await self.login():
            return None

        inbound = await self.get_inbound(config.INBOUND_ID)
        if not inbound:
            return None

        try:
            settings = json.loads(inbound["settings"])
            clients = settings.get("clients", [])

            protocol = inbound.get("protocol", "vless")
            stream_settings = self._get_stream_settings(inbound)
            email = f"{config.XUI_MANAGED_CLIENT_PREFIX}static_{profile_name}_{random.randint(100, 999)}"
            new_client = self._build_client(protocol, email, 0)

            clients.append(new_client)
            settings["clients"] = clients

            if await self.update_inbound(config.INBOUND_ID, self._build_update_data(inbound, settings)):
                return {
                    "client_id": new_client.get("id") or new_client.get("password"),
                    "password": new_client.get("password"),
                    "email": email,
                    "port": inbound["port"],
                    "protocol": protocol,
                    "network": stream_settings.get("network", "tcp"),
                    "security": stream_settings.get("security", "reality" if protocol == "vless" else "none"),
                    "remark": inbound["remark"],
                }
            return None
        except Exception as e:
            logger.exception(f"🛑 Create static client error: {e}")
            return None

    async def update_client_expiry(self, email: str, subscription_end: datetime):
        if not is_managed_client_email(email):
            logger.warning(f"Refused to update unmanaged 3x-ui client: {email}")
            return False

        if not await self.login():
            return False

        inbound = await self.get_inbound(config.INBOUND_ID)
        if not inbound:
            return False

        try:
            settings = json.loads(inbound["settings"])
            clients = settings.get("clients", [])
            expiry_time = self._datetime_to_ms(subscription_end)

            for client in clients:
                if client.get("email") == email:
                    client["expiryTime"] = expiry_time
                    if "updated_at" in client:
                        client["updated_at"] = int(time.time() * 1000)
                    settings["clients"] = clients
                    updated = await self.update_inbound(config.INBOUND_ID, self._build_update_data(inbound, settings))
                    if not updated:
                        logger.error(f"🛑 3x-ui did not accept expiry update for {email}")
                        return False

                    refreshed = await self.get_client_by_email(email)
                    if not refreshed:
                        logger.error(f"🛑 Could not verify expiry update for {email}: client not found after update")
                        return False

                    actual_expiry = int(refreshed.get("expiryTime") or 0)
                    if actual_expiry != expiry_time:
                        logger.error(
                            "🛑 3x-ui expiry verification failed for %s: expected=%s actual=%s",
                            email,
                            expiry_time,
                            actual_expiry,
                        )
                        return False

                    logger.info("✅ 3x-ui expiry verified for %s: %s", email, expiry_time)
                    return True

            logger.error(f"🛑 Client {email} not found in inbound {config.INBOUND_ID}")
            return False
        except Exception as e:
            logger.exception(f"🛑 Update client expiry error: {e}")
            return False

    async def delete_client(self, email: str):
        if not is_managed_client_email(email):
            logger.warning(f"Refused to delete unmanaged 3x-ui client: {email}")
            return False

        if not await self.login():
            return False

        inbound = await self.get_inbound(config.INBOUND_ID)
        if not inbound:
            return False

        try:
            settings = json.loads(inbound["settings"])
            clients = settings.get("clients", [])
            new_clients = [client for client in clients if client.get("email") != email]

            if len(clients) == len(new_clients):
                return False

            settings["clients"] = new_clients
            return await self.update_inbound(config.INBOUND_ID, self._build_update_data(inbound, settings))
        except Exception as e:
            logger.exception(f"🛑 Delete client error: {e}")
            return False

    async def get_user_stats(self, email: str):
        if not is_managed_client_email(email):
            logger.warning(f"Ignored unmanaged 3x-ui traffic stats lookup: {email}")
            return {"upload": 0, "download": 0}

        if not await self.login():
            return {"upload": 0, "download": 0}
        res = await self._request("GET", f"/getClientTraffics/{email}")
        if res:
            return {"upload": res.get("up", 0), "download": res.get("down", 0)}
        return {"upload": 0, "download": 0}

    async def get_online_users(self):
        if not await self.login():
            return 0
        res = await self._request("POST", "/onlines")
        if res and isinstance(res, list):
            return len([user for user in res if config.XUI_MANAGED_CLIENT_PREFIX in str(user)])
        return 0

    async def close(self):
        if self.session:
            await self.session.close()


async def create_vless_profile(telegram_id: int, subscription_end: datetime | None = None):
    api = XUIAPI()
    try:
        return await api.create_vless_profile(telegram_id, subscription_end)
    finally:
        await api.close()


async def create_static_client(profile_name: str):
    api = XUIAPI()
    try:
        return await api.create_static_client(profile_name)
    finally:
        await api.close()


async def delete_client_by_email(email: str):
    api = XUIAPI()
    try:
        return await api.delete_client(email)
    finally:
        await api.close()


async def update_client_expiry_by_email(email: str, subscription_end: datetime):
    api = XUIAPI()
    try:
        return await api.update_client_expiry(email, subscription_end)
    finally:
        await api.close()


async def get_client_by_email(email: str):
    api = XUIAPI()
    try:
        return await api.get_client_by_email(email)
    finally:
        await api.close()


async def get_global_stats():
    api = XUIAPI()
    try:
        return await api.get_global_stats(config.INBOUND_ID)
    finally:
        await api.close()


async def get_online_users():
    api = XUIAPI()
    try:
        return await api.get_online_users()
    finally:
        await api.close()


async def get_user_stats(email: str):
    api = XUIAPI()
    try:
        return await api.get_user_stats(email)
    finally:
        await api.close()


def generate_vless_url(profile_data: dict) -> str:
    email = profile_data["email"]
    encoded_remark = quote(f"{config.XUI_SERVER_NAME}-{email}")
    protocol = profile_data.get("protocol", "vless")
    network = profile_data.get("network", "tcp")
    security = profile_data.get("security", "reality" if protocol == "vless" else "none")

    if protocol == "trojan":
        password = profile_data.get("password") or profile_data["client_id"]
        return (
            f"trojan://{password}@{config.XUI_HOST}:{profile_data['port']}"
            f"?type={network}&security={security}#{encoded_remark}"
        )

    pbk = config.REALITY_PUBLIC_KEY.strip()
    fp = config.REALITY_FINGERPRINT.strip()
    sni = config.REALITY_SNI.split(",")[0].strip()
    sid = config.REALITY_SHORT_ID.split(",")[0].strip()

    return (
        f"vless://{profile_data['client_id']}@{config.XUI_HOST}:{profile_data['port']}"
        f"?type={network}&security={security}&pbk={pbk}&fp={fp}"
        f"&sni={sni}&sid={sid}&spx=%2F#{encoded_remark}"
    )
