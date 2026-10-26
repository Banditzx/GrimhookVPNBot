import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta

from sqlalchemy import func, text

import database
from database import AdminAccount, AdminSession


PASSWORD_ITERATIONS = 600_000
SESSION_TTL = timedelta(days=7)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PASSWORD_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    if not isinstance(password, str) or len(password) > 256:
        return False
    try:
        algorithm, iterations, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or not 100_000 <= int(iterations) <= 2_000_000:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations),
        )
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError, AttributeError):
        return False


def ensure_admin_account():
    with database.Session() as session:
        # Serialize the initial seed across bot and web-panel processes.
        session.execute(text("BEGIN IMMEDIATE"))
        if session.query(AdminAccount.id).first() is None:
            session.add(AdminAccount(username="admin", password_hash=hash_password("admin")))
        session.commit()


def authenticate_admin(username: str, password: str) -> dict | None:
    if not isinstance(username, str) or len(username) > 80:
        return None
    with database.Session() as session:
        account = session.query(AdminAccount).filter(
            func.lower(AdminAccount.username) == username.strip().lower(),
            AdminAccount.is_active.is_(True),
        ).first()
        if not account or not verify_password(password, account.password_hash):
            return None
        account.last_login_at = datetime.utcnow()
        result = {"id": account.id, "username": account.username, "created_at": account.created_at}
        session.commit()
        return result


def create_admin_session(admin_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    with database.Session.begin() as session:
        account = session.query(AdminAccount).filter_by(id=admin_id, is_active=True).first()
        if not account:
            raise ValueError("Учетная запись недоступна")
        session.query(AdminSession).filter(AdminSession.expires_at <= now).delete(synchronize_session=False)
        session.add(AdminSession(
            admin_id=admin_id,
            token_hash=hashlib.sha256(token.encode("ascii")).hexdigest(),
            expires_at=now + SESSION_TTL,
        ))
    return token


def get_admin_session(token: str | None) -> dict | None:
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        return None
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    with database.Session() as session:
        row = session.query(AdminAccount, AdminSession).join(
            AdminSession, AdminAccount.id == AdminSession.admin_id,
        ).filter(
            AdminSession.token_hash == digest,
            AdminSession.expires_at > datetime.utcnow(),
            AdminAccount.is_active.is_(True),
        ).first()
        if not row:
            return None
        account, admin_session = row
        return {
            "id": account.id, "username": account.username,
            "created_at": account.created_at, "expires_at": admin_session.expires_at,
        }


def delete_admin_session(token: str | None):
    if not token:
        return
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with database.Session.begin() as session:
        session.query(AdminSession).filter_by(token_hash=digest).delete(synchronize_session=False)


def change_admin_password(admin_id: int, current_password: str, new_password: str) -> bool:
    if not isinstance(new_password, str) or not 8 <= len(new_password) <= 256:
        raise ValueError("Новый пароль должен содержать от 8 до 256 символов")
    with database.Session() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        account = session.query(AdminAccount).filter_by(id=admin_id, is_active=True).first()
        if not account or not verify_password(current_password, account.password_hash):
            return False
        account.password_hash = hash_password(new_password)
        session.query(AdminSession).filter_by(admin_id=admin_id).delete(synchronize_session=False)
        session.commit()
        return True
