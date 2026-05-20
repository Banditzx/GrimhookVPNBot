import math
import os
from pathlib import Path
from typing import Dict, List

from pydantic import BaseModel, Field, field_validator

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(path):
        if not path.exists():
            return False
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            os.environ.setdefault(key.strip(), value)
        return True


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config(BaseModel):
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_PANEL_PASSWORD: str = os.getenv("ADMIN_PANEL_PASSWORD", "")
    ADMINS: List[int] = Field(default_factory=list)

    XUI_API_URL: str = os.getenv("XUI_API_URL", "")
    XUI_BASE_PATH: str = os.getenv("XUI_BASE_PATH", "")
    XUI_USERNAME: str = os.getenv("XUI_USERNAME", "")
    XUI_TOKEN: str = os.getenv("XUI_TOKEN", "")
    XUI_HOST: str = os.getenv("XUI_HOST", "")
    XUI_SERVER_NAME: str = os.getenv("XUI_SERVER_NAME", "VPN_SERVER")
    INBOUND_ID: int = int(os.getenv("INBOUND_ID", "1"))
    TRIAL_DAYS: int = int(os.getenv("TRIAL_DAYS", "1"))
    XUI_MANAGED_CLIENT_PREFIX: str = os.getenv("XUI_MANAGED_CLIENT_PREFIX", "user_")

    REALITY_PUBLIC_KEY: str = os.getenv("REALITY_PUBLIC_KEY", "")
    REALITY_FINGERPRINT: str = os.getenv("REALITY_FINGERPRINT", "chrome")
    REALITY_SNI: str = os.getenv("REALITY_SNI", "")
    REALITY_SHORT_ID: str = os.getenv("REALITY_SHORT_ID", "")
    REALITY_SPIDER_X: str = os.getenv("REALITY_SPIDER_X", "/")

    SUBSCRIPTION_PLANS: Dict[str, Dict[str, int | str]] = Field(
        default_factory=lambda: {
            "1d": {
                "label": "1 день",
                "duration_days": 1,
                "price_rub": int(os.getenv("PRICE_1_DAY_RUB", "25")),
                "discount_percent": int(os.getenv("DISCOUNT_1_DAY_PERCENT", "0")),
            },
            "7d": {
                "label": "7 дней",
                "duration_days": 7,
                "price_rub": int(os.getenv("PRICE_7_DAYS_RUB", "125")),
                "discount_percent": int(os.getenv("DISCOUNT_7_DAYS_PERCENT", "0")),
            },
            "1m": {
                "label": "1 месяц",
                "duration_days": 30,
                "price_rub": int(os.getenv("PRICE_1_MONTH_RUB", "350")),
                "discount_percent": int(os.getenv("DISCOUNT_1_MONTH_PERCENT", "0")),
            },
            "2m": {
                "label": "2 месяца",
                "duration_days": 60,
                "price_rub": int(os.getenv("PRICE_2_MONTHS_RUB", "700")),
                "discount_percent": int(os.getenv("DISCOUNT_2_MONTHS_PERCENT", "0")),
            },
            "3m": {
                "label": "3 месяца",
                "duration_days": 90,
                "price_rub": int(os.getenv("PRICE_3_MONTHS_RUB", "1050")),
                "discount_percent": int(os.getenv("DISCOUNT_3_MONTHS_PERCENT", "0")),
            },
        }
    )
    PLAN_ORDER: tuple[str, ...] = ("1d", "7d", "1m", "2m", "3m")

    STAR_RUB_RATE: float = float(os.getenv("STAR_RUB_RATE", "1.66"))
    STAR_PRICE_MARKUP_PERCENT: float = float(os.getenv("STAR_PRICE_MARKUP_PERCENT", "10"))

    @field_validator("ADMINS", mode="before")
    @classmethod
    def parse_admins(cls, value):
        if isinstance(value, str):
            return [int(admin.strip()) for admin in value.split(",") if admin.strip()]
        if isinstance(value, int):
            return [value]
        return value or []

    @field_validator("INBOUND_ID", "TRIAL_DAYS", mode="before")
    @classmethod
    def parse_int(cls, value):
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return value

    @field_validator("STAR_RUB_RATE", "STAR_PRICE_MARKUP_PERCENT", mode="before")
    @classmethod
    def parse_float(cls, value):
        if isinstance(value, str):
            return float(value)
        return value

    def get_plan(self, plan_id: str) -> dict[str, int | str] | None:
        return self.SUBSCRIPTION_PLANS.get(plan_id)

    def calculate_discounted_rub_price(self, plan_id: str) -> int:
        plan = self.SUBSCRIPTION_PLANS[plan_id]
        price_rub = plan["price_rub"]
        discount_percent = plan["discount_percent"]
        return max(0, math.ceil(price_rub * (100 - discount_percent) / 100))

    def calculate_stars_from_rub(self, price_rub: int) -> int:
        price_with_markup = price_rub * (1 + self.STAR_PRICE_MARKUP_PERCENT / 100)
        return max(1, math.ceil(price_with_markup / self.STAR_RUB_RATE))

    async def calculate_base_stars_price(self, plan_id: str) -> int:
        return self.calculate_stars_from_rub(self.SUBSCRIPTION_PLANS[plan_id]["price_rub"])

    async def calculate_stars_price(self, plan_id: str) -> int:
        discounted_price = self.calculate_discounted_rub_price(plan_id)
        return self.calculate_stars_from_rub(discounted_price)


config = Config(
    ADMINS=os.getenv("ADMINS", ""),
    INBOUND_ID=os.getenv("INBOUND_ID", "1"),
)
