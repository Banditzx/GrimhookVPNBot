# 🚀 XRay VLESS/Reality Bot & Web Panel

![CodeQL](https://github.com/Banditzx/GrimhookVPNBot/actions/workflows/codeql-analysis.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python)
![Aiogram](https://img.shields.io/badge/aiogram-3.x-red?style=flat-square&logo=telegram)
![GitHub last commit](https://img.shields.io/github/last-commit/Banditzx/GrimhookVPNBot?style=flat-square&color=6f42c1)
![License](https://img.shields.io/github/license/Banditzx/GrimhookVPNBot?style=flat-square&color=28a745)

Профессиональное решение для автоматизации продаж и управления VPN-доступом. Интегрируется с панелью **3x-ui** (протокол VLESS Reality).

## ✨ Основные функции
* **Автоматизация:** Выдача настраиваемого тестового периода новым пользователям.
* **Подключение:** Генерация VLESS-ключей напрямую из бота через API 3x-ui.
* **Оплата и продление:** бот принимает оплату через Telegram Stars и автоматически продлевает подписку пользователя.
* **Помощь:** Интерактивные инструкции по настройке для Android, iOS, Windows и macOS.
* **Админ-панель:** Веб-интерфейс на Streamlit для управления пользователями, редактирования кода и просмотра логов.

## 🛠 Установка и запуск (Docker)
# Предварительные требования
Python 3.10+

Панель управления 3X-UI

Создан inbound с параметром "Безопасность Reality"

Telegram бот (созданный через @BotFather)

## 1. Клонируйте репозиторий:
```bash
git clone https://github.com/Banditzx/GrimhookVPNBot.git
cd GrimhookVPNBot
```

## 2. Запустите проект:
```bash
docker-compose up -d
```

## 3. Доступ к админ-панели: http://IP_ВАШЕГО_СЕРВЕРА:8501

# ⚙️ Ручная установка

## 1. Создайте окружение и установите зависимости:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```


## 2. Настройте конфигурацию

Создайте файл `src/.env` на основе `src/.env.example` и заполните параметры:

```env
BOT_TOKEN=telegram_bot_token_from_botfather
ADMINS=123456789
ADMIN_PANEL_PASSWORD=long_random_password
TRIAL_DAYS=1

PRICE_1_DAY_RUB=25
PRICE_7_DAYS_RUB=125
PRICE_1_MONTH_RUB=350
PRICE_2_MONTHS_RUB=700
PRICE_3_MONTHS_RUB=1050

DISCOUNT_1_DAY_PERCENT=0
DISCOUNT_7_DAYS_PERCENT=0
DISCOUNT_1_MONTH_PERCENT=0
DISCOUNT_2_MONTHS_PERCENT=0
DISCOUNT_3_MONTHS_PERCENT=0

STAR_RUB_RATE=1.66
STAR_PRICE_MARKUP_PERCENT=10

XUI_API_URL=https://your-panel-domain:2053
XUI_HOST=your-vpn-host
XUI_BASE_PATH=/your-panel-secret-path
XUI_SERVER_NAME=Grimhook VPN
XUI_TOKEN=your_3x_ui_api_token
INBOUND_ID=1
```

Основные параметры:

* `BOT_TOKEN` — токен Telegram-бота от `@BotFather`.
* `ADMINS` — Telegram ID администраторов через запятую.
* `ADMIN_PANEL_PASSWORD` — пароль для входа в веб-админку. Используйте длинный случайный пароль; без него админ-панель не откроется.
* `TRIAL_DAYS` — длительность бесплатного тестового периода в днях.
* `PRICE_*_RUB` — цены тарифов в рублях.
* `DISCOUNT_*_PERCENT` — скидки на тарифы в процентах.
* `STAR_RUB_RATE` — ручной курс рубля к Telegram Stars.
* `STAR_PRICE_MARKUP_PERCENT` — наценка к цене в Stars.
* `XUI_API_URL`, `XUI_BASE_PATH`, `XUI_HOST`, `XUI_TOKEN` — параметры доступа к панели 3x-ui.
* `INBOUND_ID` — ID inbound, где бот будет создавать VPN-профили.

Пользователь оплачивает тариф Telegram Stars. После успешной оплаты бот сохраняет платеж, продлевает подписку в базе и синхронизирует срок действия VPN-профиля в 3x-ui.

## 3. Запустите веб-панель:
```bash
streamlit run admin_panel.py
```
После запуска перейдите по адресу, который выдаст терминал (обычно порт 8501), и нажмите кнопку «Запустить бота».

## 4. В веб-панели нажмите "Запустить бота".

# 🛠 Технологический стек

Язык: Python 3.10+

Библиотека бота: aiogram 3.x

Интерфейс админки: Streamlit

База данных: SQLite

Протокол: VLESS / Trojan / Shadowsocks (зависит от настроек 3x-ui)

## 👤 Авторы:

Проект поддерживает [Banditzx](https://github.com/Banditzx).

## ⚖️ Лицензия

Этот проект распространяется под лицензией **MIT**. Это означает, что вы можете свободно использовать, копировать и изменять код, при условии сохранения уведомления об авторстве.

Подробности см. в файле [LICENSE](./LICENSE).

Telegram бот: @grimhook_vpn_bot
Связь с разработчиком: Telegram: @Blackdogz
---
*Developed by [Banditzx](https://github.com/Banditzx)*
