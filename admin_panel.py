import streamlit as st
import sqlite3
import os
import signal
import psutil
import pandas as pd
import subprocess
import time
import sys
import asyncio
import json
import html
import secrets
import csv
import io
from pathlib import Path
from datetime import datetime

import requests

# ==========================================
# КОНФИГУРАЦИЯ И ПУТИ
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(BASE_DIR, "src")
LOG_PATH = os.path.join(BASE_DIR, "bot_error.log")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from config import config
from database import (
    Base, engine, DB_PATH as BOT_DB_PATH,
    create_activation_codes, revoke_activation_code,
)
from functions import delete_client_by_email, is_managed_client_email
from admin_auth import (
    ensure_admin_account, authenticate_admin, create_admin_session,
    get_admin_session, delete_admin_session, change_admin_password,
)

DB_PATH = str(BOT_DB_PATH)
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

st.set_page_config(page_title="Grimhook VPN Admin Panel", layout="wide")

def _get_query_param(name: str):
    value = st.query_params.get(name)
    if isinstance(value, list):
        return value[0] if value else None
    return value

def logout_admin():
    delete_admin_session(_get_query_param("admin_session"))
    st.session_state.pop("admin_authenticated", None)
    st.session_state.pop("admin_auth_until", None)
    st.session_state.pop("activation_code_batch", None)
    st.query_params.pop("admin_session", None)
    st.rerun()

def require_admin_auth():
    token = _get_query_param("admin_session")
    account = get_admin_session(token)
    if account:
        return account
    st.session_state.pop("activation_code_batch", None)
    if token:
        st.query_params.pop("admin_session", None)

    st.html(
        """
        <style>
        [data-testid="stSidebar"], [data-testid="stHeader"] {
            display: none !important;
        }
        .stApp:has(.admin-login-brand) {
            background: #0f1318 !important;
        }
        [data-testid="stAppViewContainer"]:has(.admin-login-brand) {
            background: #0f1318 !important;
        }
        [data-testid="stMain"] {
            min-height: 100dvh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 24px 16px;
        }
        [data-testid="stMainBlockContainer"] {
            flex: 0 1 auto;
            width: 100% !important;
            max-width: 400px !important;
            margin: auto !important;
            padding: 0 !important;
            box-sizing: border-box;
        }
        [data-testid="stForm"] {
            padding: 28px !important;
            border: 1px solid #343b43 !important;
            border-radius: 8px;
            background: #151a20 !important;
            box-shadow: 0 18px 54px rgba(0, 0, 0, 0.3) !important;
            box-sizing: border-box;
        }
        .admin-login-brand {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 14px;
            padding-bottom: 12px;
        }
        .admin-login-mark {
            width: 52px;
            height: 52px;
            border-radius: 8px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            color: #0f1318;
            background: #ff9d4d;
            font-size: 24px;
            font-weight: 900;
            line-height: 1;
        }
        .admin-login-brand h1 {
            margin: 0 !important;
            padding: 0 !important;
            text-align: center;
            color: #f5f5f5 !important;
            font-size: 22px !important;
            line-height: 1.2;
            font-weight: 700;
            letter-spacing: 0;
            text-shadow: none !important;
            text-transform: none !important;
        }
        [data-testid="stTextInput"] label {
            color: rgba(245, 245, 245, 0.78) !important;
            font-weight: 600 !important;
            font-size: 13px !important;
        }
        [data-testid="stTextInput"] [data-baseweb="input"] {
            min-height: 44px !important;
            padding: 0 !important;
            background: #0f1318 !important;
            border: 1px solid rgba(255, 140, 60, 0.26) !important;
            border-radius: 8px !important;
        }
        [data-testid="stTextInput"] [data-baseweb="input"]:focus-within {
            border-color: rgba(255, 157, 77, 0.72) !important;
            box-shadow: 0 0 0 1px rgba(255, 157, 77, 0.14) !important;
        }
        [data-testid="stTextInput"] input {
            color: #f5f5f5 !important;
            height: 44px !important;
            padding: 0 12px !important;
            background: transparent !important;
        }
        [data-testid="stTextInput"] [data-baseweb="input"] button {
            flex: 0 0 44px !important;
            width: 44px !important;
            height: 44px !important;
            padding: 0 !important;
            margin: 0 !important;
            border: 0 !important;
            border-radius: 0 !important;
            background: transparent !important;
            color: #d3dae3 !important;
            box-shadow: none !important;
        }
        [data-testid="stFormSubmitButton"] button {
            height: 44px !important;
            border-radius: 8px !important;
            border: 1px solid rgba(255, 157, 77, 0.4) !important;
            background: #ff9d4d !important;
            color: #0f1318 !important;
            font-weight: 800 !important;
            margin-top: 4px !important;
        }
        @media (max-width: 480px) {
            [data-testid="stForm"] { padding: 24px !important; }
        }
        </style>
        """
    )

    with st.form("admin_login"):
        st.html(
            '<div class="admin-login-brand"><div class="admin-login-mark">G</div>'
            '<h1>Grimhook VPN</h1></div>'
        )
        username = st.text_input("Логин", key="login_username", max_chars=80, autocomplete="username")
        password = st.text_input("Пароль", type="password", key="login_password", max_chars=256, autocomplete="current-password")
        submitted = st.form_submit_button("Войти", width="stretch")
        if submitted:
            account = authenticate_admin(username, password)
            if account:
                st.query_params["admin_session"] = create_admin_session(account["id"])
                st.rerun()
            st.error("Неверный логин или пароль")
    st.stop()

def render_admin_profile(account: dict):
    st.header("👤 Профиль")
    st.write(f"Логин: **{account['username']}**")
    with st.form("change_admin_password", clear_on_submit=True):
        current_password = st.text_input("Текущий пароль", type="password", max_chars=256, autocomplete="current-password")
        new_password = st.text_input("Новый пароль", type="password", max_chars=256, autocomplete="new-password")
        repeated_password = st.text_input("Повторите новый пароль", type="password", max_chars=256, autocomplete="new-password")
        submitted = st.form_submit_button("Сохранить пароль")
    if submitted:
        if new_password != repeated_password:
            st.error("Новые пароли не совпадают")
            return
        try:
            changed = change_admin_password(account["id"], current_password, new_password)
        except ValueError as error:
            st.error(str(error))
            return
        if changed:
            st.query_params["admin_session"] = create_admin_session(account["id"])
            st.session_state["password_changed"] = True
            st.rerun()
        else:
            st.error("Неверный текущий пароль")

st.html(
    """
    <style>
    :root {
        --grim-bg: #0b0f14;
        --grim-panel: #131920;
        --grim-panel-dark: #0f141a;
        --grim-text: #f5f5f5;
        --grim-muted: rgba(245, 245, 245, 0.66);
        --grim-border: rgba(255, 140, 60, 0.22);
        --grim-border-strong: rgba(255, 140, 60, 0.48);
        --grim-orange: #ff8c3c;
        --grim-orange-soft: #ffb35c;
    }

    html, body, .stApp {
        background:
            radial-gradient(circle at top left, rgba(255, 140, 60, 0.11), transparent 34rem),
            radial-gradient(circle at bottom right, rgba(255, 179, 92, 0.08), transparent 30rem),
            var(--grim-bg) !important;
        color: var(--grim-text) !important;
        font-family: "Orbitron", "Segoe UI", sans-serif;
    }

    .stApp > header {
        background: rgba(11, 15, 20, 0.78) !important;
        border-bottom: 1px solid var(--grim-border);
        backdrop-filter: blur(10px);
    }

    .block-container {
        padding-top: 2rem;
        max-width: 1320px;
    }

    h1, h2, h3 {
        color: #ffffff !important;
        letter-spacing: 0.4px;
        text-transform: uppercase;
        text-shadow: 0 0 8px rgba(255, 140, 60, 0.55);
    }

    h1 {
        color: var(--grim-orange-soft) !important;
        font-weight: 800;
    }

    p, label, span, div {
        color: inherit;
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0f141a, #080b0f) !important;
        border-right: 1px solid var(--grim-border);
        box-shadow: 8px 0 30px rgba(0, 0, 0, 0.45);
    }

    [data-testid="stSidebar"] h1 {
        color: var(--grim-orange-soft) !important;
        font-size: 1.35rem;
        text-shadow: 0 0 10px rgba(255, 140, 60, 0.65);
    }

    [data-testid="stSidebar"] [role="radiogroup"] label {
        border: 1px solid transparent;
        border-radius: 8px;
        padding: 0.42rem 0.55rem;
        margin: 0.12rem 0;
        transition: border-color 0.18s ease, background 0.18s ease, color 0.18s ease;
    }

    [data-testid="stSidebar"] [role="radiogroup"] label:hover {
        background: rgba(255, 140, 60, 0.08);
        border-color: rgba(255, 140, 60, 0.22);
    }

    [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
        background: rgba(255, 140, 60, 0.14);
        border-color: var(--grim-border-strong);
        box-shadow: 0 0 16px rgba(255, 140, 60, 0.16);
    }

    [data-testid="stMetric"],
    [data-testid="stExpander"],
    [data-testid="stDataFrame"],
    .stAlert,
    div[data-testid="stForm"],
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background: linear-gradient(145deg, rgba(19, 25, 32, 0.88), rgba(11, 15, 20, 0.88)) !important;
        border: 1px solid var(--grim-border) !important;
        border-radius: 8px !important;
        box-shadow: 0 8px 28px rgba(0, 0, 0, 0.38);
    }

    [data-testid="stMetric"] {
        padding: 1rem 1.1rem;
        transition: border-color 0.18s ease, box-shadow 0.18s ease;
    }

    [data-testid="stMetric"]:hover {
        border-color: var(--grim-border-strong) !important;
        box-shadow: 0 10px 30px rgba(255, 140, 60, 0.12);
    }

    [data-testid="stMetricLabel"] p {
        color: var(--grim-muted) !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        font-size: 0.78rem;
    }

    [data-testid="stMetricValue"] {
        color: var(--grim-orange-soft) !important;
        text-shadow: 0 0 8px rgba(255, 140, 60, 0.35);
    }

    div[data-testid="stExpander"] details {
        border: none !important;
    }

    div[data-testid="stExpander"] summary {
        color: var(--grim-orange-soft) !important;
        font-weight: 800;
        text-transform: uppercase;
    }

    .stButton > button,
    .stFormSubmitButton > button,
    [data-testid="baseButton-secondary"],
    [data-testid="baseButton-primary"] {
        border-radius: 8px !important;
        border: 1px solid var(--grim-border-strong) !important;
        background: rgba(255, 140, 60, 0.08) !important;
        color: var(--grim-orange-soft) !important;
        font-weight: 800 !important;
        letter-spacing: 0.35px;
        text-transform: uppercase;
        box-shadow: none !important;
        transition: background 0.18s ease, color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
    }

    .stButton > button:hover,
    .stFormSubmitButton > button:hover {
        background: var(--grim-orange) !important;
        color: #0b0f14 !important;
        box-shadow: 0 0 16px rgba(255, 140, 60, 0.46) !important;
        transform: translateY(-1px);
    }

    input,
    textarea,
    [data-baseweb="input"] > div,
    [data-baseweb="textarea"] textarea {
        background: #131920 !important;
        border-color: rgba(255, 140, 60, 0.32) !important;
        color: #ffffff !important;
        border-radius: 8px !important;
    }

    input:focus,
    textarea:focus {
        border-color: var(--grim-orange) !important;
        box-shadow: 0 0 0 0.18rem rgba(255, 140, 60, 0.20) !important;
    }

    [data-testid="stDataFrame"] {
        overflow: hidden;
    }

    [data-testid="stDataFrame"] div {
        color: #f5f5f5;
    }

    hr {
        border-color: var(--grim-border) !important;
    }

    .stSuccess,
    .stInfo,
    .stWarning,
    .stError {
        border-radius: 8px !important;
    }

    .support-card {
        border: 1px solid var(--grim-border);
        border-radius: 8px;
        padding: 14px 16px;
        margin: 10px 0;
        background: linear-gradient(145deg, rgba(19, 25, 32, 0.82), rgba(11, 15, 20, 0.82));
        box-shadow: 0 8px 28px rgba(0, 0, 0, 0.34);
    }
    .support-card.message-new {
        border-left: 4px solid var(--grim-orange);
        background: linear-gradient(145deg, rgba(255, 140, 60, 0.13), rgba(11, 15, 20, 0.90));
    }
    .support-card.message-read {
        border-left: 4px solid rgba(255, 140, 60, 0.24);
    }
    .support-card-top {
        display: flex;
        justify-content: space-between;
        gap: 14px;
        align-items: flex-start;
        margin-bottom: 10px;
    }
    .support-name {
        font-weight: 700;
        font-size: 16px;
        line-height: 1.25;
        color: var(--grim-orange-soft);
    }
    .support-meta,
    .support-date {
        color: var(--grim-muted);
        font-size: 13px;
        margin-top: 3px;
    }
    .support-right {
        text-align: right;
        flex: 0 0 auto;
    }
    .support-status {
        display: inline-block;
        border-radius: 999px;
        padding: 3px 9px;
        font-size: 12px;
        font-weight: 700;
    }
    .support-status.status-new {
        color: #0b0f14;
        background: var(--grim-orange);
        box-shadow: 0 0 12px rgba(255, 140, 60, 0.42);
    }
    .support-status.status-read {
        color: rgba(250, 250, 250, 0.76);
        background: rgba(255, 140, 60, 0.10);
        border: 1px solid rgba(255, 140, 60, 0.18);
    }
    .support-text {
        color: rgba(250, 250, 250, 0.9);
        font-size: 15px;
        line-height: 1.45;
        white-space: normal;
    }
    .message-body {
        border: 1px solid rgba(255, 140, 60, 0.18);
        border-radius: 8px;
        padding: 12px 14px;
        background: rgba(0, 0, 0, 0.18);
        color: rgba(250, 250, 250, 0.92);
        line-height: 1.5;
        white-space: pre-wrap;
        margin: 8px 0 14px 0;
    }
    .message-label {
        color: var(--grim-orange-soft);
        font-size: 13px;
        font-weight: 700;
        margin-top: 4px;
        text-transform: uppercase;
    }
    @media (max-width: 700px) {
        .support-card-top {
            display: block;
        }
        .support-right {
            text-align: left;
            margin-top: 8px;
        }
    }
    </style>
    """
)

Base.metadata.create_all(engine)
ensure_admin_account()
current_admin = require_admin_auth()
if st.session_state.pop("password_changed", False):
    st.success("Пароль изменен. Остальные сессии завершены.")

def ensure_db():
    Base.metadata.create_all(engine)

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def telegram_api(method, params=None):
    try:
        response = requests.get(
            f"https://api.telegram.org/bot{config.BOT_TOKEN}/{method}",
            params=params or {},
            timeout=8,
        )
        return response.json()
    except Exception as e:
        return {"ok": False, "description": str(e)}

def send_telegram_message(chat_id, text):
    return telegram_api("sendMessage", {"chat_id": chat_id, "text": text})

def get_star_balance():
    data = telegram_api("getMyStarBalance")
    if data.get("ok"):
        return data.get("result", {}).get("amount", 0)
    return None

def get_star_transactions(limit=10):
    data = telegram_api("getStarTransactions", {"limit": limit})
    if data.get("ok"):
        return data.get("result", {}).get("transactions", [])
    return []

def get_today_sales(conn):
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    row = conn.execute(
        "SELECT COUNT(*) AS count, COALESCE(SUM(stars_amount), 0) AS total "
        "FROM payment_records WHERE created_at >= ?",
        (today_start.isoformat(sep=" "),),
    ).fetchone()
    return row["count"], row["total"]

def format_unix_time(value):
    if not value:
        return "-"
    try:
        return datetime.fromtimestamp(int(value)).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(value)

def format_db_time(value):
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(str(value)).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(value)

def shorten_text(value, limit=180):
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."

def format_user(user):
    if not user:
        return "-"

    name = " ".join(
        part for part in [user.get("first_name"), user.get("last_name")] if part
    ).strip()
    username = user.get("username")
    user_id = user.get("id")

    label = name or username or str(user_id or "-")
    if username and username != label:
        label = f"{label} (@{username})"
    if user_id:
        label = f"{label} | {user_id}"
    return label

def format_db_payment(row):
    username = row["username"] or ""
    return {
        "Дата": row["created_at"],
        "Пользователь": f"{row['full_name']} | {row['telegram_id']}",
        "Username": f"@{username}" if username else "-",
        "Тариф": row["plan_label"],
        "Stars": row["stars_amount"],
        "Payload": row["plan_id"],
    }

def format_star_transaction(tx):
    source = tx.get("source") or {}
    receiver = tx.get("receiver") or {}
    partner = source or receiver
    user = partner.get("user") or {}
    payload = source.get("invoice_payload") or receiver.get("invoice_payload") or "-"
    tx_type = source.get("transaction_type") or receiver.get("transaction_type") or "-"

    return {
        "Дата": format_unix_time(tx.get("date")),
        "Сумма": tx.get("amount", 0),
        "Тип": tx_type,
        "Пользователь": format_user(user),
        "Payload": payload,
        "ID": tx.get("id", "-"),
    }

def render_support_preview(msg):
    is_new = not msg["is_read"]
    status_text = "Новое" if is_new else "Прочитано"
    status_class = "status-new" if is_new else "status-read"
    border_class = "message-new" if is_new else "message-read"
    username = msg["username"] or "без username"
    message_text = shorten_text(msg["message_text"])

    st.markdown(
        f"""
        <div class="support-card {border_class}">
            <div class="support-card-top">
                <div>
                    <div class="support-name">{html.escape(str(msg["full_name"] or "Без имени"))}</div>
                    <div class="support-meta">@{html.escape(str(username))} · ID {html.escape(str(msg["telegram_id"]))}</div>
                </div>
                <div class="support-right">
                    <span class="support-status {status_class}">{status_text}</span>
                    <div class="support-date">{html.escape(format_db_time(msg["created_at"]))}</div>
                </div>
            </div>
            <div class="support-text">{html.escape(message_text)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def delete_vpn_profile(vless_profile_data):
    if not vless_profile_data:
        return "У пользователя не было VPN профиля"

    try:
        profile = json.loads(vless_profile_data)
    except Exception:
        return "VPN профиль в базе поврежден, удален только пользователь"

    email = profile.get("email")
    if not email:
        return "Email VPN профиля не найден, удален только пользователь"
    if not is_managed_client_email(email):
        return f"VPN профиль {email} не тронут: бот работает только с префиксом {config.XUI_MANAGED_CLIENT_PREFIX}"

    deleted = asyncio.run(delete_client_by_email(email))
    if deleted:
        return f"VPN профиль {email} удален из 3x-ui"
    return f"VPN профиль {email} не найден или не удален из 3x-ui"

# Проверка статуса бота
def get_bot_status():
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            cmd = proc.info.get('cmdline')
            if cmd and any('src/app.py' in s for s in cmd):
                return proc.info['pid']
        except: continue
    return None

# --- SIDEBAR ---
with st.sidebar:
    st.title("🛡️ Grimhook VPN")
    st.caption(f"Вы вошли как {current_admin['username']}")
    if st.button("🚪 Выйти", use_container_width=True):
        logout_admin()

    menu = st.radio(
        "Навигация:",
        ["📊 Мониторинг", "💳 Транзакции", "🔑 Коды активации", "💬 Сообщения", "👥 Пользователи", "👤 Профиль", "📝 Редактор кода", "📋 Логи бота"]
    )
    
    st.divider()
    bot_pid = get_bot_status()
    if bot_pid:
        st.success(f"Бот Онлайн (PID: {bot_pid})")
        if st.button("⏹ Остановить бота", use_container_width=True):
            os.kill(bot_pid, signal.SIGTERM)
            st.rerun()
    else:
        st.error("Бот Оффлайн")
        if st.button("▶️ Запустить бота", use_container_width=True):
            subprocess.Popen(["python3", os.path.join(SRC_DIR, "app.py")], 
                             stdout=open(LOG_PATH, "a"), stderr=open(LOG_PATH, "a"), start_new_session=True)
            time.sleep(2)
            st.rerun()

# --- МЕНЮ: МОНИТОРИНГ ---
if menu == "📊 Мониторинг":
    st.header("📊 Мониторинг")
    ensure_db()
    conn = get_conn()
    try:
        total_users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        active_users = conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE subscription_end > ?",
            (datetime.utcnow().isoformat(sep=" "),),
        ).fetchone()["c"]
        today_count, today_total = get_today_sales(conn)
        unread_messages = conn.execute(
            "SELECT COUNT(*) AS c FROM support_messages WHERE is_read = 0"
        ).fetchone()["c"]

        balance = get_star_balance()
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Stars баланс", balance if balance is not None else "Ошибка")
        col2.metric("Продаж сегодня", today_count)
        col3.metric("Stars сегодня", today_total)
        col4.metric("Новых сообщений", unread_messages)

        col5, col6 = st.columns(2)
        col5.metric("Всего пользователей", total_users)
        col6.metric("Активных подписок", active_users)

        st.subheader("Последние обращения")
        messages = conn.execute(
            "SELECT * FROM support_messages ORDER BY created_at DESC LIMIT 5"
        ).fetchall()
        if messages:
            for msg in messages:
                render_support_preview(msg)
        else:
            st.caption("Обращений пока нет")
    finally:
        conn.close()

# --- МЕНЮ: ТРАНЗАКЦИИ ---
elif menu == "💳 Транзакции":
    st.header("💳 Транзакции и Stars")
    ensure_db()
    conn = get_conn()
    try:
        balance = get_star_balance()
        today_count, today_total = get_today_sales(conn)
        total_row = conn.execute(
            "SELECT COUNT(*) AS count, COALESCE(SUM(stars_amount), 0) AS total FROM payment_records"
        ).fetchone()

        col1, col2, col3 = st.columns(3)
        col1.metric("Баланс Stars", balance if balance is not None else "Ошибка")
        col2.metric("Stars сегодня", today_total)
        col3.metric("Stars всего в базе", total_row["total"])

        st.subheader("Продажи из базы бота")
        rows = conn.execute(
            "SELECT * FROM payment_records ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        if rows:
            st.dataframe(
                pd.DataFrame([format_db_payment(row) for row in rows]),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("Оплат в базе пока нет")

        st.subheader("Последние Telegram Stars транзакции")
        transactions = get_star_transactions(limit=10)
        if transactions:
            st.dataframe(
                pd.DataFrame([format_star_transaction(tx) for tx in transactions]),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("Telegram Stars транзакций пока нет")
    finally:
        conn.close()

elif menu == "🔑 Коды активации":
    st.header("🔑 Коды активации")
    ensure_db()
    conn = get_conn()
    try:
        counts = conn.execute(
            "SELECT COUNT(*) AS total, "
            "COALESCE(SUM(used_at IS NULL AND revoked_at IS NULL), 0) AS available, "
            "COALESCE(SUM(used_at IS NOT NULL), 0) AS used FROM activation_codes"
        ).fetchone()
        col1, col2, col3 = st.columns(3)
        col1.metric("Всего кодов", counts["total"])
        col2.metric("Доступно", counts["available"])
        col3.metric("Активировано", counts["used"])

        st.subheader("Создать коды")
        with st.form("create_activation_codes"):
            duration_col, quantity_col = st.columns(2)
            months = duration_col.selectbox("Срок, месяцев", list(range(1, 13)))
            quantity = quantity_col.number_input("Количество", min_value=1, max_value=100, value=1, step=1)
            note = st.text_input("Примечание к партии", max_chars=200)
            st.caption("Один месяц — 30 дней. Каждый код можно активировать один раз.")
            submitted = st.form_submit_button("Создать коды", use_container_width=True)
        if submitted:
            try:
                codes = create_activation_codes(months, int(quantity), note)
            except Exception:
                st.error("Не удалось создать коды. Повторите попытку.")
            else:
                export = io.StringIO(newline="")
                writer = csv.writer(export)
                writer.writerow(["code", "months", "days"])
                writer.writerows((code, months, months * 30) for code in codes)
                st.session_state["activation_code_batch"] = {
                    "codes": codes, "months": months, "csv": export.getvalue(),
                    "filename": f"vpn-codes-{datetime.utcnow():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}.csv",
                }
                st.rerun()

        batch = st.session_state.get("activation_code_batch")
        if batch:
            st.success(f"Создано кодов: {len(batch['codes'])}. Срок: {batch['months']} мес.")
            st.warning("Скачайте ключи перед выходом. В базе полные ключи не хранятся, восстановить их нельзя.")
            st.code("\n".join(batch["codes"]), language=None)
            download_col, clear_col = st.columns(2)
            download_col.download_button(
                "Скачать CSV", batch["csv"].encode("utf-8-sig"),
                file_name=batch["filename"], mime="text/csv", use_container_width=True,
            )
            if clear_col.button("Скрыть созданные ключи", use_container_width=True):
                del st.session_state["activation_code_batch"]
                st.rerun()

        st.subheader("История кодов")
        status = st.selectbox("Статус", ["Все", "Доступные", "Активированные", "Отозванные"])
        search = st.text_input("Поиск по окончанию ключа, Telegram ID или примечанию", max_chars=200).strip()
        conditions = []
        params = []
        if status == "Доступные":
            conditions.append("used_at IS NULL AND revoked_at IS NULL")
        elif status == "Активированные":
            conditions.append("used_at IS NOT NULL")
        elif status == "Отозванные":
            conditions.append("revoked_at IS NOT NULL")
        if search:
            conditions.append("(instr(code_hint, ?) > 0 OR instr(COALESCE(note, ''), ?) > 0 OR CAST(used_by AS TEXT) = ?)")
            params.extend([search.upper(), search, search])
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        rows = conn.execute(
            "SELECT * FROM activation_codes" + where + " ORDER BY id DESC LIMIT 200", params,
        ).fetchall()
        if rows:
            st.dataframe(pd.DataFrame([{
                "ID": row["id"], "Код": row["code_hint"], "Месяцев": row["months"],
                "Статус": "Активирован" if row["used_at"] else "Отозван" if row["revoked_at"] else "Доступен",
                "Примечание": row["note"] or "", "Создан (UTC)": format_db_time(row["created_at"]),
                "Telegram ID": str(row["used_by"]) if row["used_by"] is not None else "",
                "Активирован (UTC)": format_db_time(row["used_at"]),
                "Подписка после активации (UTC)": format_db_time(row["subscription_end"]),
                "Отозван (UTC)": format_db_time(row["revoked_at"]),
            } for row in rows]), use_container_width=True, hide_index=True)
            st.caption("Последние 200 кодов по выбранному фильтру.")
            available = {row["id"]: row for row in rows if not row["used_at"] and not row["revoked_at"]}
            if available:
                with st.form("revoke_activation_code"):
                    selected = st.selectbox(
                        "Код для отзыва", list(available),
                        format_func=lambda key: f"#{key} · {available[key]['code_hint']} · {available[key]['months']} мес.",
                    )
                    revoke = st.form_submit_button("Отозвать код")
                if revoke:
                    if revoke_activation_code(selected):
                        st.rerun()
                    else:
                        st.warning("Код уже активирован или отозван. Обновите страницу.")
        else:
            st.caption("Кодов по выбранному фильтру нет.")
    finally:
        conn.close()

# --- МЕНЮ: СООБЩЕНИЯ ---
elif menu == "💬 Сообщения":
    st.header("💬 Сообщения администратору")
    ensure_db()
    conn = get_conn()
    try:
        messages = conn.execute(
            "SELECT * FROM support_messages ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
        if messages:
            for msg in messages:
                status = "Новое" if not msg["is_read"] else "Прочитано"
                username = f"@{msg['username']}" if msg["username"] else "без username"
                title = (
                    f"{status}: {msg['full_name']} | {username} | ID {msg['telegram_id']} | "
                    f"{format_db_time(msg['created_at'])}"
                )

                with st.expander(title, expanded=not msg["is_read"]):
                    col_user, col_status = st.columns([3, 1])
                    with col_user:
                        st.markdown(f"**Пользователь:** {msg['full_name']}")
                        st.caption(f"{username} · Telegram ID: {msg['telegram_id']}")
                    with col_status:
                        if msg["is_read"]:
                            st.success("Прочитано")
                        else:
                            st.warning("Новое")

                    st.markdown('<div class="message-label">Входящее сообщение</div>', unsafe_allow_html=True)
                    st.markdown(
                        f'<div class="message-body">{html.escape(str(msg["message_text"] or ""))}</div>',
                        unsafe_allow_html=True,
                    )

                    with st.form(key=f"reply_form_{msg['id']}", clear_on_submit=False):
                        reply_text = st.text_area(
                            "Ваш ответ пользователю",
                            key=f"reply_text_{msg['id']}",
                            height=130,
                            placeholder="Напишите ответ. Он уйдет пользователю в Telegram от имени бота.",
                        )
                        sent = st.form_submit_button("📨 Отправить ответ в Telegram", use_container_width=True)

                    if sent:
                        if not reply_text.strip():
                            st.warning("Введите текст ответа перед отправкой")
                        else:
                            result = send_telegram_message(msg["telegram_id"], reply_text.strip())
                            if result.get("ok"):
                                conn.execute("UPDATE support_messages SET is_read = 1 WHERE id = ?", (msg["id"],))
                                conn.commit()
                                st.success("Ответ отправлен, сообщение отмечено прочитанным")
                                st.rerun()
                            else:
                                st.error(f"Не удалось отправить ответ: {result.get('description')}")

                    if not msg["is_read"]:
                        if st.button("Отметить прочитанным без ответа", key=f"read_{msg['id']}", use_container_width=True):
                            conn.execute("UPDATE support_messages SET is_read = 1 WHERE id = ?", (msg["id"],))
                            conn.commit()
                            st.rerun()
        else:
            st.caption("Сообщений пока нет")
    finally:
        conn.close()

# --- МЕНЮ: ПОЛЬЗОВАТЕЛИ ---
elif menu == "👥 Пользователи":
    st.header("👥 База данных пользователей")
    ensure_db()
    conn = get_conn()
    try:
        users = conn.execute("SELECT * FROM users").fetchall()
        for row in users:
            with st.expander(f"👤 {row['full_name']} (ID: {row['telegram_id']})"):
                with st.form(key=f"edit_form_{row['id']}"):
                    f_name = st.text_input("Имя", value=row['full_name'])
                    u_name = st.text_input("Username", value=row['username'] or "")
                    s_end = st.text_input("Подписка до", value=str(row['subscription_end'] or ""))
                    is_adm = st.checkbox("Права администратора", value=bool(row['is_admin']))
                    
                    if st.form_submit_button("💾 Сохранить"):
                        subscription_value = s_end.strip() or None
                        conn.execute("UPDATE users SET full_name=?, username=?, is_admin=?, subscription_end=? WHERE id=?", 
                                     (f_name, u_name, 1 if is_adm else 0, subscription_value, row['id']))
                        conn.commit()
                        st.success("Данные обновлены")
                        st.rerun()
                
                # Кнопка удаления пользователя
                if st.button(f"🗑 Удалить {row['telegram_id']}", key=f"del_{row['id']}"):
                    vpn_delete_message = delete_vpn_profile(row['vless_profile_data'])
                    conn.execute("DELETE FROM users WHERE id=?", (row['id'],))
                    conn.commit()
                    st.warning("Пользователь удален")
                    st.info(vpn_delete_message)
                    time.sleep(1)
                    st.rerun()
    finally:
        conn.close()

elif menu == "👤 Профиль":
    render_admin_profile(current_admin)

# --- МЕНЮ: РЕДАКТОР ---
elif menu == "📝 Редактор кода":
    st.header("📝 Редактор файлов")
    files = [f for f in os.listdir(SRC_DIR) if f.endswith('.py')]
    target = st.selectbox("Файл:", files)
    path = os.path.join(SRC_DIR, target)
    with open(path, "r", encoding="utf-8") as f: content = f.read()
    new_content = st.text_area("Код:", content, height=500)
    if st.button("💾 Сохранить"):
        with open(path, "w", encoding="utf-8") as f: f.write(new_content)
        st.success("Файл обновлен!")

# --- МЕНЮ: ЛОГИ ---
elif menu == "📋 Логи бота":
    st.header("📋 Журнал событий")
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, "r") as f:
            st.code(f.read()[-5000:], language="text")
