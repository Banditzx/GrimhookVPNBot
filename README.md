# 🚀 XRay VLESS/Reality Bot & Web Panel

![CodeQL](https://github.com/HOLKus/3X-UI-TGShopBot/actions/workflows/codeql-analysis.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python)
![Aiogram](https://img.shields.io/badge/aiogram-3.x-red?style=flat-square&logo=telegram)
![GitHub last commit](https://img.shields.io/github/last-commit/HOLKus/3X-UI-TGShopBot?style=flat-square&color=6f42c1)
![License](https://img.shields.io/github/license/HOLKus/3X-UI-TGShopBot?style=flat-square&color=28a745)

Профессиональное решение для автоматизации продаж и управления VPN-доступом. Интегрируется с панелью **3x-ui** (протокол VLESS Reality).

## ✨ Основные функции
* **Автоматизация:** Выдача настраиваемого тестового периода новым пользователям.
* **Подключение:** Генерация VLESS-ключей напрямую из бота через API 3x-ui.
* **Оплата:** Интегрированная платежная система через Telegram Stars.
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
git clone https://github.com/HOLKus/3X-UI-TGShopBot.git
cd 3X-UI-TGShopBot
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

Настройка конфигурации
Создайте файл src/.env на основе src/.env.example и заполните следующие поля:
BOT_TOKEN — токен вашего бота от @BotFather.
ADMIN_PANEL_PASSWORD — пароль для входа в веб-админку. Используйте длинный случайный пароль; без него админ-панель не откроется.
TRIAL_DAYS — длительность бесплатного тестового периода в днях.
Цены подписок задаются в рублях через PRICE_1_DAY_RUB, PRICE_7_DAYS_RUB, PRICE_1_MONTH_RUB, PRICE_2_MONTHS_RUB, PRICE_3_MONTHS_RUB.
Скидки задаются процентами через DISCOUNT_1_DAY_PERCENT, DISCOUNT_7_DAYS_PERCENT, DISCOUNT_1_MONTH_PERCENT, DISCOUNT_2_MONTHS_PERCENT, DISCOUNT_3_MONTHS_PERCENT.
Бот конвертирует их в Telegram Stars по ручному курсу STAR_RUB_RATE и добавляет наценку STAR_PRICE_MARKUP_PERCENT.
Параметры доступа к вашей панели 3x-ui: адрес панели, базовый путь, хост и API-токен XUI_TOKEN.

## 2. Запустите веб-панель:
```bash
streamlit run admin_panel.py
```
После запуска перейдите по адресу, который выдаст терминал (обычно порт 8501), и нажмите кнопку «Запустить бота».

## 3. В веб-панели настройте токены и нажмите "Запустить бота".

# 🛠 Технологический стек

Язык: Python 3.10+

Библиотека бота: aiogram 3.x

Интерфейс админки: Streamlit

База данных: SQLite

Протокол: VLESS / Trojan / Shadowsocks (зависит от настроек 3x-ui)

## 👤 Авторы:

Проект собран на базе https://github.com/QueenDekim/XRay-bot

Переработал и добавил WEB-Panel - https://github.com/HOLKus/

## ⚖️ Лицензия

Этот проект распространяется под лицензией **MIT**. Это означает, что вы можете свободно использовать, копировать и изменять код, при условии сохранения уведомления об авторстве.

Подробности см. в файле [LICENSE](./LICENSE).

Demo - Полностью функциональный бот: Telegram: @ReduNet_bot
Связь с разработчиком: Telegram: @Redulum
---
*Developed with ❤️ by [HOLKus](https://github.com/HOLKus)*
