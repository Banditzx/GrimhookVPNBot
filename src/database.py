from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, func, text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timedelta
from pathlib import Path
import os
import json
import logging
import hashlib
import re
import secrets
from config import config

logger = logging.getLogger(__name__)

Base = declarative_base()
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("BOT_DATABASE_PATH", BASE_DIR / "users.db"))
if not DB_PATH.is_absolute():
    DB_PATH = BASE_DIR / DB_PATH
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True)
    full_name = Column(String)
    username = Column(String)
    registration_date = Column(DateTime, default=datetime.utcnow)
    subscription_end = Column(DateTime)
    vless_profile_id = Column(String)
    vless_profile_data = Column(String)
    is_admin = Column(Boolean, default=False)
    notified = Column(Boolean, default=False)

class StaticProfile(Base):
    __tablename__ = 'static_profiles'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    vless_url = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class PaymentRecord(Base):
    __tablename__ = 'payment_records'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer)
    full_name = Column(String)
    username = Column(String)
    plan_id = Column(String)
    plan_label = Column(String)
    stars_amount = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

class SupportMessage(Base):
    __tablename__ = 'support_messages'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer)
    full_name = Column(String)
    username = Column(String)
    message_text = Column(Text)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class ActivationCode(Base):
    __tablename__ = 'activation_codes'
    id = Column(Integer, primary_key=True)
    code_hash = Column(String(64), unique=True, nullable=False)
    code_hint = Column(String, nullable=False)
    months = Column(Integer, nullable=False)
    note = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    used_at = Column(DateTime)
    used_by = Column(Integer, index=True)
    subscription_end = Column(DateTime)
    revoked_at = Column(DateTime)

class AdminAccount(Base):
    __tablename__ = 'admin_accounts'
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login_at = Column(DateTime)

class AdminSession(Base):
    __tablename__ = 'admin_sessions'
    id = Column(Integer, primary_key=True)
    admin_id = Column(Integer, nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
Session = sessionmaker(bind=engine)

def create_activation_codes(months: int, quantity: int = 1, note: str = "") -> list[str]:
    if type(months) is not int or not 1 <= months <= 12:
        raise ValueError("Срок должен быть от 1 до 12 месяцев")
    if type(quantity) is not int or not 1 <= quantity <= 100:
        raise ValueError("Количество должно быть от 1 до 100")
    if len(note) > 200:
        raise ValueError("Примечание не должно превышать 200 символов")

    codes = []
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    with Session.begin() as session:
        for _ in range(quantity):
            secret = "".join(secrets.choice(alphabet) for _ in range(20))
            code = "GVPN-" + "-".join(secret[i:i + 4] for i in range(0, 20, 4))
            normalized = code.replace("-", "")
            session.add(ActivationCode(
                code_hash=hashlib.sha256(normalized.encode("ascii")).hexdigest(),
                code_hint=f"GVPN-****-{secret[-4:]}",
                months=months,
                note=note.strip(),
            ))
            codes.append(code)
    return codes

def redeem_activation_code(telegram_id: int, code: str) -> dict:
    if not isinstance(code, str) or len(code) > 100:
        return {"status": "invalid"}
    normalized = re.sub(r"[\s-]", "", code).upper()
    if not re.fullmatch(r"GVPN[A-HJ-NP-Z2-9]{20}", normalized):
        return {"status": "invalid"}
    digest = hashlib.sha256(normalized.encode("ascii")).hexdigest()

    with Session() as session:
        # SQLite serializes writers before we read the code or subscription.
        session.execute(text("BEGIN IMMEDIATE"))
        record = session.query(ActivationCode).filter_by(code_hash=digest).first()
        if not record:
            return {"status": "invalid"}
        if record.used_at is not None:
            return {"status": "used"}
        if record.revoked_at is not None:
            return {"status": "revoked"}
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user:
            return {"status": "user_missing"}

        now = datetime.utcnow()
        start = max(user.subscription_end or now, now)
        user.subscription_end = start + timedelta(days=record.months * 30)
        user.notified = False
        record.used_at = now
        record.used_by = telegram_id
        record.subscription_end = user.subscription_end
        result = {
            "status": "activated", "months": record.months,
            "subscription_end": user.subscription_end,
        }
        code_id = record.id
        session.commit()
        logger.info("Activation code %s redeemed by user %s", code_id, telegram_id)
        return result

def revoke_activation_code(code_id: int) -> bool:
    with Session.begin() as session:
        changed = session.query(ActivationCode).filter(
            ActivationCode.id == code_id,
            ActivationCode.used_at.is_(None),
            ActivationCode.revoked_at.is_(None),
        ).update({ActivationCode.revoked_at: datetime.utcnow()}, synchronize_session=False)
        return changed == 1

def cleanup_invalid_datetime_values():
    """Normalize empty datetime strings before ORM DateTime processors read them."""
    datetime_columns = {
        "users": ("registration_date", "subscription_end"),
        "static_profiles": ("created_at",),
        "payment_records": ("created_at",),
        "support_messages": ("created_at",),
        "activation_codes": ("created_at", "used_at", "subscription_end", "revoked_at"),
    }
    with engine.begin() as connection:
        for table_name, columns in datetime_columns.items():
            for column_name in columns:
                result = connection.execute(
                    text(f"UPDATE {table_name} SET {column_name} = NULL WHERE {column_name} = ''")
                )
                if result.rowcount:
                    logger.warning(
                        "Fixed %s empty datetime values in %s.%s",
                        result.rowcount,
                        table_name,
                        column_name,
                    )

async def init_db():
    Base.metadata.create_all(engine)
    from admin_auth import ensure_admin_account
    ensure_admin_account()
    cleanup_invalid_datetime_values()
    with Session() as session:
        users = session.query(User).filter(User.subscription_end != None).all()
        reset_count = 0
        for user in users:
            has_profile = bool(user.vless_profile_data)
            has_payments = session.query(func.count(PaymentRecord.id)).filter_by(telegram_id=user.telegram_id).scalar() > 0
            has_codes = session.query(ActivationCode.id).filter_by(used_by=user.telegram_id).first() is not None
            if not has_profile and not has_payments and not has_codes:
                user.subscription_end = None
                user.notified = False
                reset_count += 1
        if reset_count:
            session.commit()
            logger.info(f"✅ Reset unused trial dates for {reset_count} users")
    logger.info("✅ Database tables created")

async def get_user(telegram_id: int):
    with Session() as session:
        return session.query(User).filter_by(telegram_id=telegram_id).first()

async def create_user(telegram_id: int, full_name: str, username: str = None, is_admin: bool = False):
    with Session() as session:
        user = User(
            telegram_id=telegram_id,
            full_name=full_name,
            username=username,
            subscription_end=None,
            is_admin=is_admin
        )
        session.add(user)
        session.commit()
        logger.info(f"✅ New user created: {telegram_id}")
        return user

async def delete_user_profile(telegram_id: int):
    with Session() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if user:
            user.vless_profile_data = None
            user.notified = False
            session.commit()
            logger.info(f"✅ User profile deleted: {telegram_id}")

async def mark_user_profile_deleted(telegram_id: int):
    with Session() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user:
            return False

        profile_data = {}
        if user.vless_profile_data:
            try:
                profile_data = json.loads(user.vless_profile_data)
            except Exception:
                profile_data = {"raw_profile_data": user.vless_profile_data}

        profile_data["xui_deleted"] = True
        profile_data["xui_deleted_at"] = datetime.utcnow().isoformat(sep=" ")
        user.vless_profile_data = json.dumps(profile_data, ensure_ascii=False)
        user.notified = False
        session.commit()
        logger.info(f"✅ User VPN profile marked as deleted in 3x-ui: {telegram_id}")
        return True

async def update_subscription_days(telegram_id: int, days: int):
    """Обновляет подписку с учетом текущего состояния"""
    with Session() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if user:
            now = datetime.utcnow()
            # Если подписка активна, добавляем к текущей дате окончания.
            # Если даты еще нет или срок истек, начинаем от текущего момента.
            if user.subscription_end and user.subscription_end > now:
                user.subscription_end += timedelta(days=days)
            else:
                user.subscription_end = now + timedelta(days=days)
            
            # Сбрасываем флаг уведомления
            user.notified = False
            session.commit()
            logger.info(f"✅ Subscription updated for {telegram_id}: +{days} days")
            return True
        return False

async def activate_trial_subscription(telegram_id: int):
    """Starts the free trial from the first real connection attempt."""
    with Session() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user:
            return None

        user.subscription_end = datetime.utcnow() + timedelta(days=config.TRIAL_DAYS)
        user.notified = False
        session.commit()
        logger.info(f"✅ Trial subscription activated for {telegram_id}: {config.TRIAL_DAYS} days")
        return user.subscription_end

async def update_subscription(telegram_id: int, months: int):
    return await update_subscription_days(telegram_id, months * 30)

async def get_all_users(with_subscription: bool = None):
    with Session() as session:
        query = session.query(User)
        if with_subscription is not None:
            if with_subscription:
                query = query.filter(User.subscription_end > datetime.utcnow())
            else:
                query = query.filter((User.subscription_end == None) | (User.subscription_end <= datetime.utcnow()))
        return query.all()

async def create_static_profile(name: str, vless_url: str):
    with Session() as session:
        profile = StaticProfile(name=name, vless_url=vless_url)
        session.add(profile)
        session.commit()
        logger.info(f"✅ Static profile created: {name}")
        return profile

async def get_static_profiles():
    with Session() as session:
        return session.query(StaticProfile).all()

async def get_user_stats():
    with Session() as session:
        total = session.query(func.count(User.id)).scalar()
        with_sub = session.query(func.count(User.id)).filter(User.subscription_end > datetime.utcnow()).scalar()
        without_sub = total - with_sub
        return total, with_sub, without_sub

async def has_payment_records(telegram_id: int) -> bool:
    with Session() as session:
        return session.query(func.count(PaymentRecord.id)).filter_by(telegram_id=telegram_id).scalar() > 0

async def has_redeemed_codes(telegram_id: int) -> bool:
    with Session() as session:
        return session.query(ActivationCode.id).filter_by(used_by=telegram_id).first() is not None

async def create_payment_record(
    telegram_id: int,
    full_name: str,
    username: str | None,
    plan_id: str,
    plan_label: str,
    stars_amount: int,
):
    with Session() as session:
        record = PaymentRecord(
            telegram_id=telegram_id,
            full_name=full_name,
            username=username,
            plan_id=plan_id,
            plan_label=plan_label,
            stars_amount=stars_amount,
        )
        session.add(record)
        session.commit()
        logger.info(f"✅ Payment record saved: {telegram_id}, {plan_id}, {stars_amount} stars")
        return record

async def create_support_message(
    telegram_id: int,
    full_name: str,
    username: str | None,
    message_text: str,
):
    with Session() as session:
        record = SupportMessage(
            telegram_id=telegram_id,
            full_name=full_name,
            username=username,
            message_text=message_text,
        )
        session.add(record)
        session.commit()
        logger.info(f"✅ Support message saved: {telegram_id}")
        return record
