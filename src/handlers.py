import asyncio
import logging
import json
from datetime import datetime, timedelta
from aiogram import Dispatcher, Router, F, Bot
from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config
from database import (
    StaticProfile, get_user, create_user, update_subscription_days, 
    get_all_users, create_static_profile, get_static_profiles, 
    User, Session, get_user_stats as db_user_stats,
    create_payment_record, create_support_message, mark_user_profile_deleted, activate_trial_subscription, has_payment_records
)
from functions import create_vless_profile, delete_client_by_email, generate_vless_url, get_user_stats, create_static_client, get_global_stats, get_online_users, update_client_expiry_by_email, get_client_by_email, is_managed_client_email

logger = logging.getLogger(__name__)

router = Router()

MAX_MESSAGE_LENGTH = 4096

class AdminStates(StatesGroup):
    ADD_TIME = State()
    REMOVE_TIME = State()
    CREATE_STATIC_PROFILE = State()
    SEND_MESSAGE = State()
    ADD_TIME_USER = State()
    REMOVE_TIME_USER = State()
    ADD_TIME_AMOUNT = State()
    REMOVE_TIME_AMOUNT = State()
    SEND_MESSAGE_TARGET = State()
    SUPPORT_MESSAGE = State()

def split_text(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> list:
    """Разбивает текст на части указанной максимальной длины"""
    if len(text) <= max_length:
        return [text]
    
    parts = []
    while text:
        if len(text) <= max_length:
            parts.append(text)
            break
        part = text[:max_length]
        last_newline = part.rfind('\n')
        if last_newline != -1:
            part = part[:last_newline]
        parts.append(part)
        text = text[len(part):].lstrip()
    return parts

async def sync_vpn_expiry(vless_profile_data: str, subscription_end: datetime) -> bool:
    profile_data = safe_json_loads(vless_profile_data, default={})
    email = profile_data.get("email")
    if not is_managed_client_email(email):
        logger.warning(f"Skip unmanaged 3x-ui profile sync: {email}")
        return True
    return await update_client_expiry_by_email(email, subscription_end)

async def save_user_profile_data(telegram_id: int, profile_data: dict) -> User | None:
    with Session() as session:
        db_user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if db_user:
            db_user.vless_profile_data = json.dumps(profile_data, ensure_ascii=False)
            session.commit()
    return await get_user(telegram_id)

async def show_menu(bot: Bot, chat_id: int, message_id: int = None):
    """Функция для отображения меню (может как редактировать существующее сообщение, так и отправлять новое)"""
    user = await get_user(chat_id)
    if not user:
        return

    is_active = bool(user.subscription_end and user.subscription_end > datetime.utcnow())
    status = "активна" if is_active else "не активна"
    expire_date = user.subscription_end.strftime("%d.%m.%Y %H:%M") if user.subscription_end else "нет данных"

    text = (
        "👋 **Grimhook VPN**\n\n"
        f"Подписка сейчас **{status}**.\n"
        f"Дата окончания: `{expire_date}`\n\n"
        "Для подключения используйте кнопку ниже. Если подписка закончится и вы оплатите снова, "
        "бот выдаст новую рабочую ссылку для подключения."
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="⭐ Продлить" if is_active else "⭐ Купить подписку", callback_data="renew_sub")
    builder.button(text="🔌 Подключиться", callback_data="connect")
    builder.button(text="📋 Статус", callback_data="status")
    builder.button(text="📊 Трафик", callback_data="stats")
    builder.button(text="💬 Написать админу", callback_data="support_message")
    builder.button(text="ℹ️ Помощь", callback_data="help")

    if user.is_admin:
        builder.button(text="⚠️ Админ. меню", callback_data="admin_menu")

    builder.adjust(2, 2, 2, 1)

    if message_id:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=builder.as_markup(),
            parse_mode='Markdown'
        )
    else:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=builder.as_markup(),
            parse_mode='Markdown'
        )

@router.message(Command("start"))
async def start_cmd(message: Message, bot: Bot):
    logger.info(f"ℹ️  Start command from {message.from_user.id}")
    user = await get_user(message.from_user.id)
    
    # Обновляем данные пользователя если они изменились
    update_data = {}
    if user:
        if user.full_name != message.from_user.full_name:
            update_data["full_name"] = message.from_user.full_name
        if user.username != message.from_user.username:
            update_data["username"] = message.from_user.username
    else:
        is_admin = message.from_user.id in config.ADMINS
        user = await create_user(
            telegram_id=message.from_user.id, 
            full_name=message.from_user.full_name,
            username=message.from_user.username,
            is_admin=is_admin
        )
        trial_suffix = "день" if config.TRIAL_DAYS == 1 else "дня" if config.TRIAL_DAYS in (2, 3, 4) else "дней"
        await message.answer(
            f"Добро пожаловать в VPN бота `{(await bot.get_me()).full_name}`!\n"
            f"Бесплатный тестовый период на **{config.TRIAL_DAYS} {trial_suffix}** начнется, когда вы впервые нажмете **Подключиться**.",
            parse_mode='Markdown'
        )
        await asyncio.sleep(2)
    
    # Обновляем данные если есть изменения
    if update_data:
        with Session() as session:
            db_user = session.query(User).get(user.id)
            for key, value in update_data.items():
                setattr(db_user, key, value)
            session.commit()
            logger.info(f"🔄 Updated user data: {message.from_user.id}")
    
    await show_menu(bot, message.from_user.id)

@router.message(Command("menu"))
async def menu_cmd(message: Message, bot: Bot):
    user = await get_user(message.from_user.id)
    if not user:
        await start_cmd(message, bot)
        return
    
    # Проверяем изменения данных
    update_data = {}
    if user.full_name != message.from_user.full_name:
        update_data["full_name"] = message.from_user.full_name
    if user.username != message.from_user.username:
        update_data["username"] = message.from_user.username
    
    # Обновляем данные если есть изменения
    if update_data:
        with Session() as session:
            db_user = session.query(User).get(user.id)
            for key, value in update_data.items():
                setattr(db_user, key, value)
            session.commit()
            logger.info(f"🔄 Updated user data in menu: {message.from_user.id}")
    
    await show_menu(bot, message.from_user.id)

def build_help_text() -> str:
    return (
        "О боте:\n"
        "<b>Поддержка:</b> support@grimhook.org\n"
        "<b>Telegram бот:</b> @grimhook_vpn_bot"
    )

@router.message(Command("help"))
async def help_cmd(message: Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="back_to_menu")
    await message.answer(build_help_text(), parse_mode="HTML", reply_markup=builder.as_markup())

@router.callback_query(F.data == "help")
async def help_msg(callback: CallbackQuery):
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="back_to_menu")
    await callback.message.answer(build_help_text(), parse_mode="HTML", reply_markup=builder.as_markup())

@router.message(Command("paysupport"))
async def pay_support_cmd(message: Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 Написать админу", callback_data="support_message")
    builder.button(text="⬅️ Открыть меню", callback_data="back_to_menu")
    builder.adjust(1)
    await message.answer(
        "💳 <b>Оплата другим способом</b>\n\n"
        "VPN можно оплатить переводом на карту. "
        "Для получения реквизитов и ручного продления подписки воспользуйтесь кнопкой «Написать админу».\n\n"
        "В сообщении укажите нужный тариф и ваш Telegram ID.",
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )

@router.callback_query(F.data == "support_message")
async def support_message_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="back_to_menu")
    await callback.message.edit_text(
        "💬 Напишите сообщение для администратора одним сообщением:",
        reply_markup=builder.as_markup()
    )
    await state.set_state(AdminStates.SUPPORT_MESSAGE)

@router.message(AdminStates.SUPPORT_MESSAGE)
async def process_support_message(message: Message, state: FSMContext, bot: Bot):
    text = message.text or message.caption
    if not text:
        await message.answer("Пожалуйста, отправьте текстовое сообщение.")
        return

    await create_support_message(
        telegram_id=message.from_user.id,
        full_name=message.from_user.full_name,
        username=message.from_user.username,
        message_text=text,
    )

    admin_text = (
        "💬 Новое сообщение администратору\n\n"
        f"От: {message.from_user.full_name} | {message.from_user.id}\n"
        f"Username: @{message.from_user.username or 'none'}\n\n"
        f"{text}"
    )
    for admin_id in config.ADMINS:
        try:
            await bot.send_message(admin_id, admin_text)
        except Exception as e:
            logger.error(f"🛑 Failed to send support message to admin {admin_id}: {e}")

    await message.answer("✅ Сообщение отправлено администратору.")
    await state.clear()
    await show_menu(bot, message.from_user.id)

@router.callback_query(F.data == "renew_sub")
async def renew_subscription(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    
    for plan_id in config.PLAN_ORDER:
        plan = config.get_plan(plan_id)
        if not plan:
            continue

        discount_percent = plan.get("discount_percent", 0)
        stars_price = await config.calculate_stars_price(plan_id)
        if discount_percent:
            base_stars_price = await config.calculate_base_stars_price(plan_id)
            button_text = f"{plan['label']} - {stars_price} ⭐ вместо {base_stars_price} ⭐ (-{discount_percent}%)"
        else:
            button_text = f"{plan['label']} - {stars_price} ⭐"
        builder.button(text=button_text, callback_data=f"pay_{plan_id}")
    
    builder.button(text="⬅️ Назад", callback_data="back_to_menu")
    builder.adjust(1)
    
    await callback.message.edit_text(
        "⭐ **Выберите период подписки:**",
        reply_markup=builder.as_markup(),
        parse_mode='Markdown'
    )

@router.callback_query(F.data.startswith("pay_"))
async def process_payment(callback: CallbackQuery, bot: Bot):
    await callback.answer()
    
    try:
        plan_id = callback.data.split("_", 1)[1]
        plan = config.get_plan(plan_id)
        if not plan:
            await callback.message.answer("❌ Неверный период подписки")
            return
            
        stars_price = await config.calculate_stars_price(plan_id)
        # Telegram Stars use XTR and integer star amounts without kopecks/cents.
        prices = [LabeledPrice(label=f"VPN подписка на {plan['label']}", amount=stars_price)]
        await bot.send_invoice(
            chat_id=callback.from_user.id,
            title=f"VPN подписка на {plan['label']}",
            description=f"Доступ к VPN сервису на {plan['label']}",
            payload=f"subscription_{plan_id}",
            provider_token="",
            currency="XTR",
            prices=prices,
            start_parameter="create_subscription",
            need_phone_number=False
        )
    except Exception as e:
        logger.error(f"🛑 Payment error: {e}")
        await callback.message.answer("❌ Ошибка при создании счета на оплату")

@router.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: PreCheckoutQuery, bot: Bot):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@router.message(F.successful_payment)
async def process_successful_payment(message: Message, bot: Bot):
    try:
        # Извлекаем информацию из payload
        payload = message.successful_payment.invoice_payload
        if payload.startswith("subscription_"):
            plan_id = payload.split("_", 1)[1]
            plan = config.get_plan(plan_id)
            if not plan:
                await message.answer("❌ Ошибка: тариф не найден")
                return

            stars_price = message.successful_payment.total_amount
            
            # Получаем информацию о пользователе
            user = await get_user(message.from_user.id)
            if not user:
                await message.answer("❌ Ошибка: пользователь не найден")
                return
            
            # Определяем тип действия (покупка или продление).
            # У новых пользователей subscription_end может быть пустым до первого подключения.
            now = datetime.utcnow()
            old_subscription_end = user.subscription_end
            action_type = "продлена" if old_subscription_end and old_subscription_end > now else "куплена"
            logger.info(
                "Payment received: user=%s payload=%s plan=%s days=%s stars=%s old_end=%s",
                message.from_user.id,
                payload,
                plan_id,
                plan["duration_days"],
                message.successful_payment.total_amount,
                old_subscription_end,
            )

            # Обновляем подписку
            success = await update_subscription_days(message.from_user.id, int(plan["duration_days"]))
            if success:
                await create_payment_record(
                    telegram_id=message.from_user.id,
                    full_name=message.from_user.full_name,
                    username=message.from_user.username,
                    plan_id=plan_id,
                    plan_label=plan["label"],
                    stars_amount=stars_price,
                )
                updated_user = await get_user(message.from_user.id)
                logger.info(
                    "Subscription updated after payment: user=%s old_end=%s new_end=%s plan=%s",
                    message.from_user.id,
                    old_subscription_end,
                    updated_user.subscription_end if updated_user else None,
                    plan_id,
                )
                vpn_sync_ok = True
                vpn_sync_text = ""
                if updated_user and updated_user.vless_profile_data:
                    profile_data = safe_json_loads(updated_user.vless_profile_data, default={})
                    email = profile_data.get("email")
                    if profile_data.get("xui_deleted"):
                        vpn_sync_text = "\n\nℹ️ Рабочий VPN профиль будет создан при следующем нажатии «Подключить» на оплаченный срок."
                    else:
                        client = await get_client_by_email(email) if email else False
                        if client is False:
                            await mark_user_profile_deleted(updated_user.telegram_id)
                            vpn_sync_text = "\n\nℹ️ Старый VPN профиль отсутствует в панели. При следующем подключении бот создаст новый профиль на оплаченный срок."
                        elif client is None:
                            vpn_sync_ok = False
                            vpn_sync_text = "\n\n⚠️ Подписка в боте продлена, но 3x-ui временно недоступна для проверки профиля. Попробуйте подключиться позже."
                        else:
                            vpn_sync_ok = await sync_vpn_expiry(updated_user.vless_profile_data, updated_user.subscription_end)
                            logger.info(
                                "3x-ui sync after payment: user=%s email=%s new_end=%s ok=%s",
                                updated_user.telegram_id,
                                email,
                                updated_user.subscription_end,
                                vpn_sync_ok,
                            )
                            if not vpn_sync_ok:
                                vpn_sync_text = "\n\n⚠️ Подписка в боте продлена, но срок VPN профиля не обновился. Напишите администратору."

                await message.answer(
                    f"✅ Оплата прошла успешно! Ваша подписка {action_type} на {plan['label']}.\n\n"
                    f"Спасибо за покупку! 🎉{vpn_sync_text}"
                )
                
                # Отправляем уведомление администраторам
                admin_message = (
                    f"{action_type.capitalize()} подписка пользователем "
                    f"`{user.full_name}` | `{user.telegram_id}` "
                    f"на {plan['label']} - {stars_price} ⭐"
                )
                
                for admin_id in config.ADMINS:
                    try:
                        await bot.send_message(admin_id, admin_message, parse_mode='Markdown')
                    except Exception as e:
                        logger.error(f"🛑 Failed to send notification to admin {admin_id}: {e}")
            else:
                await message.answer("❌ Ошибка при обновлении подписки")
    except Exception as e:
        logger.exception(f"🛑 Successful payment processing error: {e}")
        try:
            await message.answer(
                "⚠️ Оплата получена, но при продлении возникла ошибка. "
                "Администратор уже получил уведомление, подписку нужно проверить вручную."
            )
        except Exception:
            pass

        for admin_id in config.ADMINS:
            try:
                await bot.send_message(
                    admin_id,
                    "🛑 Ошибка обработки успешной оплаты\n"
                    f"Пользователь: `{message.from_user.full_name}` | `{message.from_user.id}`\n"
                    f"Ошибка: `{e}`",
                    parse_mode="Markdown",
                )
            except Exception as notify_error:
                logger.error(f"🛑 Failed to notify admin {admin_id} about payment error: {notify_error}")

@router.callback_query(F.data == "admin_menu")
async def admin_menu(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    if not user or not user.is_admin:
        await callback.answer("🛑 Доступ запрещен!")
        return
    
    total, with_sub, without_sub = await db_user_stats()
    online_count = await get_online_users()
    
    text = (
        "**Административное меню**\n\n"
        f"**Всего пользователей**: `{total}`\n"
        f"**С подпиской/Без подписки**: `{with_sub}`/`{without_sub}`\n"
        f"**Онлайн**: `{online_count}` | **Офлайн**: `{with_sub - online_count}`"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="+ время", callback_data="admin_add_time")
    builder.button(text="- время", callback_data="admin_remove_time")
    builder.button(text="📋 Список пользователей", callback_data="admin_user_list")
    builder.button(text="📊 Статистика исп. сети", callback_data="admin_network_stats")
    builder.button(text="📢 Рассылка", callback_data="admin_send_message")
    builder.button(text="⬅️ Назад", callback_data="back_to_menu")
    builder.adjust(2, 1, 1, 1, 1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode='Markdown')

# Обработчики для управления временем подписки
@router.callback_query(F.data == "admin_add_time")
async def admin_add_time_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()  # Снимаем анимацию
    await callback.message.answer("Введите Telegram ID пользователя:")
    await state.set_state(AdminStates.ADD_TIME_USER)

@router.message(AdminStates.ADD_TIME_USER)
async def admin_add_time_user(message: Message, state: FSMContext):
    try:
        user_id = int(message.text)
        await state.update_data(user_id=user_id)
        await message.answer("Введите количество времени в формате:\nМесяцы Дни Часы Минуты\nПример: 1 0 0 0")
        await state.set_state(AdminStates.ADD_TIME_AMOUNT)
    except ValueError:
        await message.answer("Ошибка: ID должен быть числом")

@router.message(AdminStates.ADD_TIME_AMOUNT)
async def admin_add_time_amount(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = data['user_id']
    parts = message.text.split()
    
    if len(parts) != 4:
        await message.answer("Ошибка: нужно ввести 4 числа")
        return
    
    try:
        months, days, hours, minutes = map(int, parts)
        total_seconds = (
            months * 30 * 24 * 60 * 60 +
            days * 24 * 60 * 60 +
            hours * 60 * 60 +
            minutes * 60
        )
        
        with Session() as session:
            user = session.query(User).filter_by(telegram_id=user_id).first()
            if user:
                if user.subscription_end and user.subscription_end > datetime.utcnow():
                    user.subscription_end += timedelta(seconds=total_seconds)
                else:
                    user.subscription_end = datetime.utcnow() + timedelta(seconds=total_seconds)
                vless_profile_data = user.vless_profile_data
                subscription_end = user.subscription_end
                session.commit()
                vpn_sync_ok = await sync_vpn_expiry(vless_profile_data, subscription_end)
                await message.answer(f"✅ Добавлено время пользователю {user_id}")
                if not vpn_sync_ok:
                    await message.answer("⚠️ Время в базе обновлено, но срок VPN профиля в 3x-ui не синхронизировался")
            else:
                await message.answer("❌ Пользователь не найден")
    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}")
    finally:
        await state.clear()

@router.callback_query(F.data == "admin_remove_time")
async def admin_remove_time_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()  # Снимаем анимацию
    await callback.message.answer("Введите Telegram ID пользователя:")
    await state.set_state(AdminStates.REMOVE_TIME_USER)

@router.message(AdminStates.REMOVE_TIME_USER)
async def admin_remove_time_user(message: Message, state: FSMContext):
    try:
        user_id = int(message.text)
        await state.update_data(user_id=user_id)
        await message.answer("Введите количество времени в формате:\nМесяцы Дни Часы Минуты\nПример: 1 0 0 0")
        await state.set_state(AdminStates.REMOVE_TIME_AMOUNT)
    except ValueError:
        await message.answer("Ошибка: ID должен быть числом")

@router.message(AdminStates.REMOVE_TIME_AMOUNT)
async def admin_remove_time_amount(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = data['user_id']
    parts = message.text.split()
    
    if len(parts) != 4:
        await message.answer("Ошибка: нужно ввести 4 числа")
        return
    
    try:
        months, days, hours, minutes = map(int, parts)
        total_seconds = (
            months * 30 * 24 * 60 * 60 +
            days * 24 * 60 * 60 +
            hours * 60 * 60 +
            minutes * 60
        )
        
        with Session() as session:
            user = session.query(User).filter_by(telegram_id=user_id).first()
            if user:
                if not user.subscription_end:
                    await message.answer("❌ У пользователя еще нет активной даты подписки")
                    return
                new_end = user.subscription_end - timedelta(seconds=total_seconds)
                # Проверяем, чтобы не ушло в прошлое
                if new_end < datetime.utcnow():
                    new_end = datetime.utcnow()
                user.subscription_end = new_end
                vless_profile_data = user.vless_profile_data
                subscription_end = user.subscription_end
                session.commit()
                vpn_sync_ok = await sync_vpn_expiry(vless_profile_data, subscription_end)
                await message.answer(f"✅ Удалено время у пользователя {user_id}")
                if not vpn_sync_ok:
                    await message.answer("⚠️ Время в базе обновлено, но срок VPN профиля в 3x-ui не синхронизировался")
            else:
                await message.answer("❌ Пользователь не найден")
    except Exception as e:
        await message.answer(f"Ошибка: {str(e)}")
    finally:
        await state.clear()

# Обработчики для вывода списка пользователей
@router.callback_query(F.data == "admin_user_list")
async def admin_user_list(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ С подпиской", callback_data="user_list_active")
    builder.button(text="🛑 Без подписки", callback_data="user_list_inactive")
    builder.button(text="⏱️ Статические профили", callback_data="static_profiles_menu")
    builder.button(text="⬅️ Назад", callback_data="admin_menu")
    builder.adjust(1, 1, 1)
    await callback.message.edit_text("**Выберите фильтр**", reply_markup=builder.as_markup(), parse_mode='Markdown')

@router.callback_query(F.data == "user_list_active")
async def handle_user_list_active(callback: CallbackQuery):
    users = await get_all_users(with_subscription=True)
    await callback.answer()
    if not users:
        await callback.answer("Нет пользователей с активной подпиской")
        return
    
    text = "👤 <b>Пользователи с активной подпиской:</b>\n\n"
    for user in users:
        expire_date = user.subscription_end.strftime("%d.%m.%Y %H:%M")
        username = f"@{user.username}" if user.username else "none"
        user_line = f"• {user.full_name} ({username} | <code>{user.telegram_id}</code>) - до <code>{expire_date}</code>\n"
        
        # Если текст становится слишком длинным, отправляем текущую часть и начинаем новую
        if len(text) + len(user_line) > MAX_MESSAGE_LENGTH:
            await callback.message.answer(text, parse_mode="HTML")
            text = "👤 <b>Пользователи с активной подпиской (продолжение):</b>\n\n"
        
        text += user_line
    
    # Отправляем оставшуюся часть текста
    await callback.message.answer(text, parse_mode="HTML")

@router.callback_query(F.data == "user_list_inactive")
async def handle_user_list_inactive(callback: CallbackQuery):
    await callback.answer()
    users = await get_all_users(with_subscription=False)
    if not users:
        await callback.answer("Нет пользователей без подписки")
        return
    
    text = "👤 <b>Пользователи без подписки:</b>\n\n"
    for user in users:
        username = f"@{user.username}" if user.username else "none"
        user_line = f"• {user.full_name} ({username} | <code>{user.telegram_id}</code>)\n"
        
        # Если текст становится слишком длинным, отправляем текущую часть и начинаем новую
        if len(text) + len(user_line) > MAX_MESSAGE_LENGTH:
            await callback.message.answer(text, parse_mode="HTML")
            text = "👤 <b>Пользователи без подписки (продолжение):</b>\n\n"
        
        text += user_line
    
    # Отправляем оставшуюся часть текста
    await callback.message.answer(text, parse_mode="HTML")

# Обработчики для рассылки сообщений
@router.callback_query(F.data == "admin_send_message")
async def admin_send_message_start(callback: CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ С подпиской", callback_data="target_active")
    builder.button(text="🛑 Без подписки", callback_data="target_inactive")
    builder.button(text="👥 Всем пользователям", callback_data="target_all")
    builder.button(text="↩️ Назад", callback_data="admin_menu")
    builder.adjust(1)
    
    await callback.message.edit_text(
        "Выберите целевую аудиторию для рассылки:",
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data.startswith("target_"))
async def admin_send_message_target(callback: CallbackQuery, state: FSMContext):
    await callback.answer()  # Снимаем анимацию
    target = callback.data.split("_")[1]
    await state.update_data(target=target)
    await callback.message.answer("Введите сообщение для рассылки:")
    await state.set_state(AdminStates.SEND_MESSAGE)

@router.message(AdminStates.SEND_MESSAGE)
async def admin_send_message(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    target = data['target']
    text = message.text
    
    users = []
    if target == "active":
        users = await get_all_users(with_subscription=True)
    elif target == "inactive":
        users = await get_all_users(with_subscription=False)
    else:  # all
        users = await get_all_users()
    
    success = 0
    failed = 0
    
    for user in users:
        try:
            await bot.send_message(user.telegram_id, text)
            success += 1
        except Exception as e:
            logger.error(f"🛑 Ошибка отправки сообщения {user.telegram_id}: {e}")
            failed += 1
    
    await message.answer(
        f"📨 Результаты рассылки:\n\n"
        f"• Успешно: {success}\n"
        f"• Не удалось: {failed}\n"
        f"• Всего: {len(users)}"
    )
    await state.clear()

# Остальные обработчики остаются без изменений
@router.callback_query(F.data == "static_profiles_menu")
async def static_profiles_menu(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="🆕 Добавить статический профиль", callback_data="static_profile_add")
    builder.button(text="📋 Вывести статические профили", callback_data="static_profile_list")
    builder.button(text="⬅️ Назад", callback_data="admin_user_list")
    builder.adjust(1)
    await callback.message.edit_text("**Выберите действие**", reply_markup=builder.as_markup(), parse_mode='Markdown')

@router.callback_query(F.data == "static_profile_add")
async def static_profile_add(callback: CallbackQuery, state: FSMContext):
    await callback.answer()  # Снимаем анимацию
    await callback.message.answer("Введите имя для статического профиля:")
    await state.set_state(AdminStates.CREATE_STATIC_PROFILE)

@router.message(AdminStates.CREATE_STATIC_PROFILE)
async def process_static_profile_name(message: Message, state: FSMContext):
    profile_name = message.text
    profile_data = await create_static_client(profile_name)
    
    if profile_data:
        vless_url = generate_vless_url(profile_data)
        await create_static_profile(profile_name, vless_url)
        profiles = await get_static_profiles()
        for profile in profiles:
            if profile.name == profile_name:
                id = profile.id
        builder = InlineKeyboardBuilder()
        builder.button(text="🗑️ Удалить", callback_data=f"delete_static_{id}")
        await message.answer(f"Профиль создан!\n\n`{vless_url}`", reply_markup=builder.as_markup(), parse_mode='Markdown')
    else:
        await message.answer("Ошибка при создании профиля")
    
    await state.clear()

@router.callback_query(F.data == "static_profile_list")
async def static_profile_list(callback: CallbackQuery):
    profiles = await get_static_profiles()
    if not profiles:
        await callback.answer("Нет статических профилей")
        return
    
    for profile in profiles:
        builder = InlineKeyboardBuilder()
        builder.button(text="🗑️ Удалить", callback_data=f"delete_static_{profile.id}")
        await callback.message.answer(
            f"**{profile.name}**\n`{profile.vless_url}`", 
            reply_markup=builder.as_markup(), parse_mode='Markdown'
        )

@router.callback_query(F.data.startswith("delete_static_"))
async def handle_delete_static_profile(callback: CallbackQuery):
    try:
        profile_id = int(callback.data.split("_")[-1])
        
        with Session() as session:
            profile = session.query(StaticProfile).filter_by(id=profile_id).first()
            if not profile:
                await callback.answer("⚠️ Профиль не найден")
                return
            
            success = await delete_client_by_email(profile.name)
            if not success:
                logger.error(f"🛑 Ошибка удаления клиента из инбаунда: {profile.name}")
            
            session.delete(profile)
            session.commit()
        
        await callback.answer("✅ Профиль удален!")
        await callback.message.delete()
    except Exception as e:
        logger.error(f"🛑 Ошибка при удалении статического профиля: {e}")
        await callback.answer("⚠️ Ошибка при удалении профиля")

@router.callback_query(F.data == "connect")
async def connect_profile(callback: CallbackQuery, bot: Bot):
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("🛑 Ошибка профиля")
        return
    
    profile_data = safe_json_loads(user.vless_profile_data, default={})
    now = datetime.utcnow()

    has_payments = await has_payment_records(user.telegram_id)

    if not profile_data and not has_payments and (not user.subscription_end or user.subscription_end <= now):
        trial_end = await activate_trial_subscription(user.telegram_id)
        if not trial_end:
            await callback.answer("🛑 Не удалось активировать пробный период", show_alert=True)
            return
        user = await get_user(user.telegram_id)
        await callback.message.answer(
            f"✅ Пробный период активирован до `{trial_end.strftime('%d.%m.%Y %H:%M')}`. Сейчас создам VPN профиль.",
            parse_mode="Markdown"
        )

    if not user.subscription_end or user.subscription_end <= datetime.utcnow():
        await callback.answer("⚠️ Подписка истекла! Продлите подписку.", show_alert=True)
        await show_menu(bot, callback.from_user.id, callback.message.message_id)
        return

    needs_new_profile = not profile_data or profile_data.get("xui_deleted")

    if profile_data and not profile_data.get("xui_deleted"):
        email = profile_data.get("email")
        client = await get_client_by_email(email) if email else False
        if client is None:
            await callback.message.answer("⚠️ Не удалось проверить профиль в 3x-ui. Попробуйте позже.")
            return
        needs_new_profile = client is False
        if needs_new_profile:
            await mark_user_profile_deleted(user.telegram_id)

    if needs_new_profile:
        await callback.message.edit_text("⚙️ Создаем рабочий VPN профиль на ваш оплаченный срок...")
        profile_data = await create_vless_profile(user.telegram_id, user.subscription_end)
        if profile_data:
            user = await save_user_profile_data(user.telegram_id, profile_data)
        else:
            await callback.message.answer("🛑 Ошибка при создании профиля. Попробуйте позже.")
            return

    if not profile_data:
        await callback.message.answer("⚠️ У вас пока нет созданного профиля. Попробуйте позже.")
        return

    vless_url = generate_vless_url(profile_data)
    text = (
        "🎉 **Ваш VPN профиль готов!**\n\n"
        "ℹ️ **Инструкция по подключению:**\n"
        "1. Скачайте приложение для вашей платформы\n"
        "2. Скопируйте эту ссылку и импортируйте в приложение:\n\n"
        f"`{vless_url}`\n\n"
        "3. Активируйте соединение в приложении."
    )

    builder = InlineKeyboardBuilder()
    builder.button(text='🖥️ Windows [V2RayN]', url='https://github.com/2dust/v2rayN/releases/download/7.13.8/v2rayN-windows-64-desktop.zip')
    builder.button(text='🐧 Linux [NekoBox]', url='https://github.com/MatsuriDayo/nekoray/releases/download/4.0.1/nekoray-4.0.1-2024-12-12-debian-x64.deb')
    builder.button(text='🍎 Mac [V2RayU]', url='https://github.com/yanue/V2rayU/releases/download/v4.2.6/V2rayU-64.dmg ')
    builder.button(text='🍏 iOS [V2RayTun]', url='https://apps.apple.com/ru/app/v2raytun/id6476628951')
    builder.button(text='🤖 Android [V2RayNG]', url='https://github.com/2dust/v2rayNG/releases/download/1.10.16/v2rayNG_1.10.16_arm64-v8a.apk')
    builder.button(text="⬅️ Назад", callback_data="back_to_menu")
    builder.adjust(2, 2, 1, 1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode='Markdown')

@router.callback_query(F.data == "stats")
async def user_stats(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    if not user or not user.vless_profile_data:
        await callback.answer("⚠️ Профиль не создан")
        return
    await callback.message.edit_text("⚙️ Загружаем вашу статистику...")
    profile_data = safe_json_loads(user.vless_profile_data, default={})
    stats = await get_user_stats(profile_data["email"])

    upload = f"{stats.get('upload', 0) / 1024 / 1024:.2f}"
    upload_size = 'MB' if int(float(upload)) < 1024 else 'GB'
    if upload_size == "GB":
        upload = f"{int(float(upload) / 1024):.2f}"

    download = f"{stats.get('download', 0) / 1024 / 1024:.2f}"
    download_size = 'MB' if int(float(download)) < 1024 else 'GB'
    if download_size == "GB":
        download = f"{int(float(download) / 1024):.2f}"

    await callback.message.delete()
    text = (
        "📊 **Ваша статистика:**\n\n"
        f"🔼 Загружено: `{upload} {upload_size}`\n"
        f"🔽 Скачано: `{download} {download_size}`\n"
    )
    await callback.message.answer(text, parse_mode='Markdown')

@router.callback_query(F.data == "admin_network_stats")
async def network_stats(callback: CallbackQuery):
    stats = await get_global_stats()

    upload = f"{stats.get('upload', 0) / 1024 / 1024:.2f}"
    upload_size = 'MB' if int(float(upload)) < 1024 else 'GB'
    if upload_size == "GB":
        upload = f"{int(float(upload) / 1024):.2f}"

    download = f"{stats.get('download', 0) / 1024 / 1024:.2f}"
    download_size = 'MB' if int(float(download)) < 1024 else 'GB'
    if download_size == "GB":
        download = f"{int(float(download) / 1024):.2f}"
    
    await callback.answer()
    text = (
        "📊 **Статистика использования сети:**\n\n"
        f"🔼 Upload - `{upload} {upload_size}` | 🔽 Download - `{download} {download_size}`"
    )
    await callback.message.edit_text(text, parse_mode='Markdown')

@router.callback_query(F.data == "status")
async def subscription_status(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("🛑 Пользователь не найден")
        return

    now = datetime.utcnow()
    is_active = bool(user.subscription_end and user.subscription_end > now)
    registration_date = user.registration_date.strftime("%d.%m.%Y %H:%M") if user.registration_date else "нет данных"
    expire_date = user.subscription_end.strftime("%d.%m.%Y %H:%M") if user.subscription_end else "нет данных"
    days_left = (user.subscription_end - now).days if is_active else 0

    profile_data = safe_json_loads(user.vless_profile_data, default={})
    if profile_data.get("xui_deleted"):
        profile_status = "профиль будет создан после оплаты/подключения"
    elif profile_data:
        profile_status = "профиль создан"
    else:
        profile_status = "профиль еще не создавался"

    status_text = "Активна" if is_active else "Не активна"
    renewal_note = (
        "Если подписка закончится, старый профиль будет отключен. "
        "После новой оплаты нажмите «Подключиться» и используйте новую ссылку в приложении."
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="⭐ Продлить" if is_active else "⭐ Купить подписку", callback_data="renew_sub")
    builder.button(text="🔌 Подключиться", callback_data="connect")
    builder.button(text="⬅️ Назад", callback_data="back_to_menu")
    builder.adjust(2, 1)

    text = (
        "📋 **Статус аккаунта**\n\n"
        f"**Подписка:** `{status_text}`\n"
        f"**Дата окончания:** `{expire_date}`\n"
        f"**Осталось дней:** `{days_left}`\n"
        f"**Дата регистрации:** `{registration_date}`\n"
        f"**Telegram ID:** `{user.telegram_id}`\n"
        f"**VPN профиль:** `{profile_status}`\n\n"
        f"ℹ️ {renewal_note}"
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.answer()
    await state.clear()
    await show_menu(bot, callback.from_user.id, callback.message.message_id)

def setup_handlers(dp: Dispatcher):
    dp.include_router(router)
    logger.info("✅ Handlers setup completed")

def safe_json_loads(data, default=None):
    if not data:
        return default
    try:
        return json.loads(data)
    except Exception:
        return default
