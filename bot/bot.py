import asyncio
import logging
import os
import json
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8753082286:AAH2IAfGsQ_X_k4oxf6Tpj2jQeWjHT6ZVJc")
ADMIN_ID  = int(os.getenv("ADMIN_ID", "5376892021"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://menervatripolska.github.io/CIAcademyTGapp/webapp")

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher()

PATTERN_NAMES = {
    1: "🔴 ПАТТЕРН 1 — АРХИВ (Отказ)",
    2: "🟠 ПАТТЕРН 2 — АНАЛИТИК (Ограниченный доступ)",
    3: "🔵 ПАТТЕРН 3 — НАВИГАТОР (Базовый допуск)",
    4: "🟢 ПАТТЕРН 4 — ОПЕРАТОР (Зелёный свет)",
    5: "⚡ ПАТТЕРН 5 — ЭЛИТА (Приоритет)",
}


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="⚡ Пройти вступительный отбор",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )
    ]])

    await message.answer(
        "🦄 <b>Kryptan Academy</b>\n\n"
        "Добро пожаловать в систему вступительного отбора.\n\n"
        "Академия не берёт всех подряд. Нам нужны те, кто психологически готов "
        "работать с реальными рисками крипто-рынка.\n\n"
        "📋 <b>Тебя ждут 5 тестов:</b>\n"
        "🎯 Тест Голланда — профессиональный тип\n"
        "🎲 Склонность к азарту — риск-профиль\n"
        "🛡️ Жизнестойкость — психологическая устойчивость\n"
        "🔭 Профориентирование — интересы и способности\n"
        "⚖️ Толерантность к неопределённости\n\n"
        "⏱ ~40 минут. Отвечай честно — это в твоих интересах.\n\n"
        "Нажми кнопку, чтобы начать:",
        reply_markup=kb,
        parse_mode="HTML"
    )


@dp.message(F.web_app_data)
async def handle_webapp_data(message: types.Message):
    """Receive test results from WebApp"""
    try:
        data = json.loads(message.web_app_data.data)
        results = data.get('results', {})
        pattern = results.get('pattern', 0)
        user = message.from_user

        # Confirm to user
        pattern_text = PATTERN_NAMES.get(pattern, f"Паттерн {pattern}")
        await message.answer(
            f"✅ <b>Результаты получены!</b>\n\n"
            f"<b>Вердикт Академии:</b>\n{pattern_text}\n\n"
            f"Куратор рассмотрит твой профиль и свяжется с тобой в ближайшее время.",
            parse_mode="HTML"
        )

        # Send detailed report to admin
        holland = results.get('holland', {})
        gambling = results.get('gambling', {})
        hardiness = results.get('hardiness', {})
        proforientation = results.get('proforientation', {})
        tolerance = results.get('tolerance', {})

        admin_text = (
            f"🆕 <b>НОВАЯ ЗАЯВКА — KRYPTAN ACADEMY</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Кандидат:</b> {user.full_name}"
            f"{f' (@{user.username})' if user.username else ''}\n"
            f"🆔 ID: <code>{user.id}</code>\n"
            f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>{pattern_text}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🎯 <b>Голланд:</b> {holland.get('topName', '—')} [{holland.get('sortedTop3', '')}]\n"
            f"🎲 <b>Азарт:</b> {gambling.get('level', '—')} ({gambling.get('score', '?')}/8)\n"
            f"🛡️ <b>Жизнестойкость:</b> {hardiness.get('total', '?')} "
            f"(В:{hardiness.get('commitment','?')} К:{hardiness.get('control','?')} Р:{hardiness.get('challenge','?')})\n"
            f"🔭 <b>Профориент.:</b> {', '.join(proforientation.get('topSpheres', ['—'])) or '—'}\n"
            f"⚖️ <b>Толерантность:</b> ТН:{tolerance.get('tn','?')} ИТН:{tolerance.get('itn','?')} МИТН:{tolerance.get('mitn','?')}\n\n"
            f"<b>Написать кандидату:</b> tg://user?id={user.id}"
        )

        # Action buttons for admin
        admin_kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Принять", callback_data=f"accept:{user.id}"),
                InlineKeyboardButton(text="❌ Отказать", callback_data=f"reject:{user.id}"),
            ],
            [
                InlineKeyboardButton(text="💬 Написать", url=f"tg://user?id={user.id}")
            ]
        ])

        await bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML", reply_markup=admin_kb)

    except Exception as e:
        logger.error(f"Error processing webapp data: {e}")
        await message.answer("Результаты приняты! Куратор скоро свяжется с тобой.")


@dp.callback_query(F.data.startswith("accept:"))
async def admin_accept(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    user_id = int(callback.data.split(":")[1])
    try:
        await bot.send_message(
            user_id,
            "🎉 <b>Поздравляем!</b>\n\n"
            "Академия приняла решение — вы прошли отборочное тестирование.\n"
            "Куратор свяжется с вами для дальнейших инструкций.\n\n"
            "Добро пожаловать в Kryptan Academy! 🦄⚡",
            parse_mode="HTML"
        )
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("✅ Кандидат уведомлён о принятии")
    except Exception as e:
        await callback.answer(f"Ошибка: {e}")


@dp.callback_query(F.data.startswith("reject:"))
async def admin_reject(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    user_id = int(callback.data.split(":")[1])
    try:
        await bot.send_message(
            user_id,
            "📋 <b>Результат рассмотрен</b>\n\n"
            "После анализа вашего профиля Академия приняла решение не выдавать "
            "доступ к активным программам на данном этапе.\n\n"
            "Это не окончательно. Работа над собой и повторное тестирование через "
            "3 месяца может изменить результат.",
            parse_mode="HTML"
        )
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("❌ Кандидат уведомлён об отказе")
    except Exception as e:
        await callback.answer(f"Ошибка: {e}")


@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(
        "🔑 <b>Панель администратора</b>\n\n"
        "Команды:\n"
        "/admin — эта панель\n\n"
        "Результаты тестирования приходят автоматически при завершении каждого кандидата.",
        parse_mode="HTML"
    )


async def main():
    logger.info("Starting Kryptan Academy Bot...")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
