from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, func
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timedelta
from pathlib import Path
import os
import json
import logging
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

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
Session = sessionmaker(bind=engine)

async def init_db():
    Base.metadata.create_all(engine)
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
            subscription_end=datetime.utcnow() + timedelta(days=config.TRIAL_DAYS),
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
            # Если подписка активна, добавляем к текущей дате окончания
            if user.subscription_end > now:
                user.subscription_end += timedelta(days=days)
            else:
                # Если подписка истекла, начинаем с текущей даты
                user.subscription_end = now + timedelta(days=days)
            
            # Сбрасываем флаг уведомления
            user.notified = False
            session.commit()
            logger.info(f"✅ Subscription updated for {telegram_id}: +{days} days")
            return True
        return False

async def update_subscription(telegram_id: int, months: int):
    return await update_subscription_days(telegram_id, months * 30)

async def get_all_users(with_subscription: bool = None):
    with Session() as session:
        query = session.query(User)
        if with_subscription is not None:
            if with_subscription:
                query = query.filter(User.subscription_end > datetime.utcnow())
            else:
                query = query.filter(User.subscription_end <= datetime.utcnow())
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
