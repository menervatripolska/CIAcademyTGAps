"""CI Academy — Telegram приёмная отбора.

Flow:
  /start → reply-кнопка "Пройти вступительный отбор" (WebApp)
  WebApp (5 тестов) → tg.sendData(payload)
  handle_webapp_data:
    1. Пишет заявку в Airtable
    2. По паттерну (1–5) автоматически шлёт кандидату свой вердикт
       - Паттерн 1 → отказ
       - Паттерны 2, 3, 4 → accept + ссылка на курс + слот-фраза
       - Паттерн 5 → spec-accept + ссылка + алерт админу
    3. Админу в любом случае приходит полный лог + кнопки override

ENV:
  BOT_TOKEN           — токен от @BotFather (обязательно)
  ADMIN_ID            — numeric id администратора (обязательно)
  WEBAPP_URL          — URL мини-аппа (default: GitHub Pages)
  COURSE_URL          — ссылка на курс (default: https://ciacademy.kz)
  AIRTABLE_API_KEY    — personal access token с scope data.records:write
  AIRTABLE_BASE_ID    — app... id базы (default: appa0lbQ8SuQvc7aV)
  AIRTABLE_TABLE_ID   — tbl... id таблицы Applicants (default: tblpPcaIPEfVswjnK)
"""
import asyncio
import csv
import io
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone

import aiohttp
import aiosqlite
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s — %(levelname)s — %(message)s"
)
log = logging.getLogger("ci-academy-bot")

# ─── env ────────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env var is required")

ADMIN_ID = int(os.getenv("ADMIN_ID", "5376892021"))
WEBAPP_URL = os.getenv(
    "WEBAPP_URL", "https://menervatripolska.github.io/CIAcademyTGAps/"
)
COURSE_URL = os.getenv("COURSE_URL", "https://ciacademy.kz")

AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID", "appa0lbQ8SuQvc7aV")
AIRTABLE_TABLE_ID = os.getenv("AIRTABLE_TABLE_ID", "tblpPcaIPEfVswjnK")

# Локальная SQLite (на Railway — в /data если смонтирован volume; иначе рядом с ботом).
DB_PATH = os.getenv("DB_PATH", "/data/applicants.db"
                    if os.path.isdir("/data") else "applicants.db")


async def db_init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS applicants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_user_id INTEGER NOT NULL,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                pattern INTEGER,
                verdict TEXT,
                course_link_sent INTEGER DEFAULT 0,
                holland_top TEXT,
                gambling_score INTEGER,
                hardiness_total INTEGER,
                profori_spheres TEXT,
                tolerance_score INTEGER,
                raw_payload TEXT,
                created_at TEXT
            )
        ''')
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_pattern ON applicants(pattern)")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_user ON applicants(tg_user_id)")
        await db.commit()
    log.info("SQLite готова: %s", DB_PATH)


async def db_insert(user, results, manual_username, pattern, verdict,
                    link_sent, raw_payload):
    holland = results.get("holland") or {}
    gambling = results.get("gambling") or {}
    hardiness = results.get("hardiness") or {}
    profori = results.get("proforientation") or {}
    tolerance = results.get("tolerance") or {}
    spheres = profori.get("topSpheres") or []
    if isinstance(spheres, list):
        spheres = ", ".join(str(x) for x in spheres)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            '''INSERT INTO applicants
               (tg_user_id, username, first_name, last_name, pattern, verdict,
                course_link_sent, holland_top, gambling_score, hardiness_total,
                profori_spheres, tolerance_score, raw_payload, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (user.id,
             (user.username or manual_username or "").lstrip("@"),
             user.first_name or "",
             user.last_name or "",
             pattern,
             verdict,
             1 if link_sent else 0,
             (holland.get("sortedTop3") or holland.get("topName") or "")[:120],
             int(gambling.get("score") or 0),
             int(hardiness.get("total") or 0),
             spheres[:500],
             int(tolerance.get("score") or 0),
             json.dumps(raw_payload, ensure_ascii=False)[:50000],
             datetime.now(timezone.utc).isoformat()))
        await db.commit()
    log.info("SQLite: +1 кандидат (id=%s, pattern=%s)", user.id, pattern)


async def db_export_csv() -> tuple[bytes, int]:
    '''Вернуть (csv_bytes, rows_count).'''
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=',', quoting=csv.QUOTE_MINIMAL)
    w.writerow([
        "id", "tg_user_id", "username", "first_name", "last_name",
        "pattern", "verdict", "course_link_sent",
        "holland_top", "gambling_score", "hardiness_total",
        "profori_spheres", "tolerance_score", "created_at",
    ])
    count = 0
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            '''SELECT id, tg_user_id, username, first_name, last_name,
                      pattern, verdict, course_link_sent,
                      holland_top, gambling_score, hardiness_total,
                      profori_spheres, tolerance_score, created_at
               FROM applicants ORDER BY id DESC''') as cur:
            async for row in cur:
                w.writerow(row); count += 1
    return buf.getvalue().encode("utf-8-sig"), count


async def db_stats() -> dict:
    stats = {"total": 0, "by_pattern": {}, "accepted": 0, "rejected": 0}
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT pattern, COUNT(*) FROM applicants GROUP BY pattern"
        ) as cur:
            async for p, c in cur:
                stats["by_pattern"][p] = c
                stats["total"] += c
                if p == 1:
                    stats["rejected"] += c
                elif p in (2, 3, 4, 5):
                    stats["accepted"] += c
    return stats


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ─── pattern metadata ───────────────────────────────────────────────────────
PATTERN_NAMES = {
    1: "🔴 ПАТТЕРН 1 — АРХИВ (Отказ)",
    2: "🟠 ПАТТЕРН 2 — АНАЛИТИК (Ограниченный доступ)",
    3: "🔵 ПАТТЕРН 3 — НАВИГАТОР (Базовый допуск)",
    4: "🟢 ПАТТЕРН 4 — ОПЕРАТОР (Зелёный свет)",
    5: "⚡ ПАТТЕРН 5 — ЭЛИТА (Приоритет)",
}

# Для Airtable singleSelect Pattern (значения должны совпадать с вариантами в таблице)
PATTERN_AT_NAMES = {
    1: "1 — Архив (Отказ)",
    2: "2 — Аналитик (Ограниченный)",
    3: "3 — Навигатор (Базовый)",
    4: "4 — Оператор (Зелёный свет)",
    5: "5 — Элита (Приоритет)",
}

# Индивидуальная фраза для accept-сообщения (патт. 2/3/4)
PATTERN_SLOT = {
    2: "системное мышление и устойчивость к давлению",
    3: "трезвая голова и навык читать рынок без эмоций",
    4: "готовность действовать и держать позицию даже в просадке",
}

# ─── /start ─────────────────────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    # sendData работает ТОЛЬКО из reply-keyboard — даём большую reply-кнопку.
    kb = ReplyKeyboardMarkup(
        keyboard=[[
            KeyboardButton(
                text="⚡ Пройти вступительный отбор",
                web_app=WebAppInfo(url=WEBAPP_URL),
            )
        ]],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Нажми кнопку ниже ⬇️",
    )
    await message.answer(
        "🦄 <b>CI Academy</b>\n\n"
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
        "Нажми кнопку ниже, чтобы начать:",
        reply_markup=kb,
        parse_mode="HTML",
    )


# ─── airtable ───────────────────────────────────────────────────────────────
async def airtable_create(fields: dict) -> str | None:
    """POST новой записи в Applicants. Возвращает record_id или None."""
    if not AIRTABLE_API_KEY:
        log.warning("AIRTABLE_API_KEY не задан — запись пропущена (только Telegram-лог).")
        return None

    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_ID}"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json",
    }
    # typecast=true → Airtable сам создаст singleSelect-опцию если её нет
    body = {"records": [{"fields": fields}], "typecast": True}

    async with aiohttp.ClientSession() as s:
        async with s.post(url, headers=headers, json=body, timeout=15) as r:
            if r.status >= 300:
                txt = await r.text()
                log.error("Airtable %s: %s", r.status, txt[:500])
                return None
            data = await r.json()
            return data["records"][0]["id"]


def build_airtable_fields(user, results: dict, manual_username: str,
                          pattern: int, verdict: str, link_sent: bool,
                          raw_payload: dict) -> dict:
    holland = results.get("holland") or {}
    gambling = results.get("gambling") or {}
    hardiness = results.get("hardiness") or {}
    profori = results.get("proforientation") or {}
    tolerance = results.get("tolerance") or {}

    profori_spheres = profori.get("topSpheres") or []
    if isinstance(profori_spheres, list):
        profori_spheres = ", ".join(str(x) for x in profori_spheres)

    return {
        "TG User ID": str(user.id),
        "Username": (user.username or manual_username or "").lstrip("@"),
        "First name": user.first_name or "",
        "Last name": user.last_name or "",
        "Pattern": PATTERN_AT_NAMES.get(pattern, f"Pattern {pattern}"),
        "Verdict": verdict,
        "Holland top": (holland.get("sortedTop3") or holland.get("topName") or "")[:120],
        "Gambling score": int(gambling.get("score") or 0),
        "Hardiness total": int(hardiness.get("total") or 0),
        "Profori spheres": profori_spheres[:500],
        "Tolerance score": int(tolerance.get("score") or 0),
        "Course link sent": bool(link_sent),
        "Created at": datetime.now(timezone.utc).isoformat(),
        "Raw results": json.dumps(raw_payload, ensure_ascii=False)[:90000],
    }


# ─── outgoing messages ──────────────────────────────────────────────────────
async def send_to_candidate(chat_id: int, pattern: int):
    """Шлёт кандидату персональный вердикт по паттерну."""
    if pattern == 1:
        await bot.send_message(
            chat_id,
            "🛡️ <b>CI Academy — результат отбора</b>\n\n"
            "Спасибо, что прошёл тесты до конца — это уже о многом говорит.\n\n"
            "По твоему психологическому профилю на данном этапе мы "
            "<b>не открываем доступ к активным программам Академии</b>. "
            "Это не про «плох/хорош», это про готовность работать с реальными "
            "рисками крипто-рынка каждый день без предохранителей.\n\n"
            "Повторный отбор возможен через <b>3 месяца</b>.",
            parse_mode="HTML",
        )
    elif pattern in (2, 3, 4):
        slot = PATTERN_SLOT[pattern]
        await bot.send_message(
            chat_id,
            "⚡ <b>Ты прошёл отбор CI Academy</b>\n\n"
            "По всем пяти тестам ты попал в группу, которую мы берём на курс "
            "«Я — Криптан». У тебя проявлена <b>"
            f"{slot}</b> — это важно для работы с рынком.\n\n"
            "Курс стартует по готовности — 8 уроков, своя Crypto OS, "
            "AI-ассистент, закрытое коммьюнити.\n\n"
            f"👉 <b>Забрать доступ:</b> {COURSE_URL}\n\n"
            "Если появятся вопросы — пиши прямо сюда.",
            parse_mode="HTML",
            disable_web_page_preview=False,
        )
    elif pattern == 5:
        await bot.send_message(
            chat_id,
            "🦄 <b>Тебя мы искали.</b>\n\n"
            "Паттерн 5 — редкое сочетание психологической устойчивости, "
            "трезвой работы с неопределённостью и готовности брать "
            "ответственность за решения. Это профиль, на который мы строим "
            "ядро комьюнити CI Academy.\n\n"
            "Тебя ждёт приоритетный маршрут: персональный куратор, приглашение "
            "в закрытый круг, ранний доступ к Crypto OS.\n\n"
            f"👉 <b>Войти в Академию:</b> {COURSE_URL}\n\n"
            "В ближайшие сутки с тобой свяжутся лично, чтобы обсудить детали.",
            parse_mode="HTML",
            disable_web_page_preview=False,
        )
    else:
        await bot.send_message(
            chat_id,
            "Результаты получены. Куратор свяжется с тобой в ближайшее время.",
        )


async def send_admin_log(user, results, pattern, verdict, airtable_id):
    """Полный отчёт админу + кнопки override."""
    holland = results.get("holland") or {}
    gambling = results.get("gambling") or {}
    hardiness = results.get("hardiness") or {}
    profori = results.get("proforientation") or {}
    tolerance = results.get("tolerance") or {}

    uname = f"@{user.username}" if user.username else "(нет @username)"
    name = " ".join(filter(None, [user.first_name, user.last_name])) or "—"

    txt = (
        f"📥 <b>Новая заявка</b>\n\n"
        f"<b>Кандидат:</b> {name} {uname}\n"
        f"<b>TG ID:</b> <code>{user.id}</code>\n"
        f"<b>Паттерн:</b> {PATTERN_NAMES.get(pattern, pattern)}\n"
        f"<b>Вердикт:</b> {verdict}\n\n"
        f"🎯 Holland: {holland.get('sortedTop3') or holland.get('topName', '—')}\n"
        f"🎲 Азарт: {gambling.get('score', '—')}/8 ({gambling.get('level', '—')})\n"
        f"🛡️ Жизнестойкость: {hardiness.get('total', '—')} "
        f"(В:{hardiness.get('commitment','—')} "
        f"К:{hardiness.get('control','—')} "
        f"Р:{hardiness.get('challenge','—')})\n"
        f"🔭 Профориентация: {', '.join(profori.get('topSpheres', [])) or '—'}\n"
        f"⚖️ Толерантность: {tolerance.get('score','—')} ({tolerance.get('level','—')})\n"
    )
    if airtable_id:
        at_link = f"https://airtable.com/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_ID}/{airtable_id}"
        txt += f"\n📊 <a href='{at_link}'>Открыть в Airtable</a>"

    # Override-кнопки — чтобы админ мог вручную переиграть авто-решение
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Написать", url=f"tg://user?id={user.id}")],
        [
            InlineKeyboardButton(text="✅ Override: Принять", callback_data=f"override_accept:{user.id}"),
            InlineKeyboardButton(text="❌ Override: Отказать", callback_data=f"override_reject:{user.id}"),
        ],
    ])
    await bot.send_message(ADMIN_ID, txt, parse_mode="HTML",
                           reply_markup=kb, disable_web_page_preview=True)

    # Приоритетный алерт для паттерна 5
    if pattern == 5:
        await bot.send_message(
            ADMIN_ID,
            f"🚨 <b>PRIORITY — PATTERN 5</b>\n\n"
            f"{name} {uname} — свяжись лично в течение 24ч.",
            parse_mode="HTML",
        )


# ─── main handler ───────────────────────────────────────────────────────────
@dp.message(F.web_app_data)
async def handle_webapp_data(message: types.Message):
    user = message.from_user
    try:
        payload = json.loads(message.web_app_data.data)
    except Exception as e:
        log.error("Bad payload from user %s: %s", user.id, e)
        await message.answer("⚠️ Не удалось прочитать результаты. Попробуй ещё раз.")
        return

    results = payload.get("results", {}) or {}
    pattern = int(results.get("pattern") or 0)
    manual_username = (payload.get("manual_username") or "").strip().lstrip("@")

    verdict = (
        "Auto-Reject" if pattern == 1 else
        "Priority (P5)" if pattern == 5 else
        "Auto-Accept" if pattern in (2, 3, 4) else
        "Manual Override"
    )
    link_sent = pattern in (2, 3, 4, 5)

    # 1a) SQLite (всегда пишется — это наш primary storage)
    try:
        await db_insert(user, results, manual_username, pattern,
                        verdict, link_sent, payload)
    except Exception as e:
        log.error("SQLite insert failed: %s", e)

    # 1b) Airtable (опционально)
    fields = build_airtable_fields(user, results, manual_username,
                                   pattern, verdict, link_sent, payload)
    airtable_id = None
    try:
        airtable_id = await airtable_create(fields)
    except Exception as e:
        log.error("Airtable write failed: %s", e)

    # 2) Кандидату — персональное сообщение + убираем reply-клавиатуру
    try:
        await message.answer(
            "✅ Результаты получены. Секунду — формируем вердикт…",
            reply_markup=ReplyKeyboardRemove(),
        )
        await send_to_candidate(user.id, pattern)
    except Exception as e:
        log.error("Candidate message failed: %s", e)

    # 3) Админу — полный лог
    try:
        await send_admin_log(user, results, pattern, verdict, airtable_id)
    except Exception as e:
        log.error("Admin log failed: %s", e)


# ─── override ───────────────────────────────────────────────────────────────
@dp.callback_query(F.data.startswith("override_accept:"))
async def admin_override_accept(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    user_id = int(cb.data.split(":")[1])
    try:
        await bot.send_message(
            user_id,
            "⚡ <b>Пересмотр решения</b>\n\n"
            "Куратор пересмотрел твой профиль — ты получаешь доступ к курсу "
            "«Я — Криптан».\n\n"
            f"👉 <b>Забрать доступ:</b> {COURSE_URL}",
            parse_mode="HTML",
        )
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.answer("✅ Отправлено override-accept")
    except Exception as e:
        await cb.answer(f"Ошибка: {e}")


@dp.callback_query(F.data.startswith("override_reject:"))
async def admin_override_reject(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    user_id = int(cb.data.split(":")[1])
    try:
        await bot.send_message(
            user_id,
            "📋 <b>Пересмотр решения</b>\n\n"
            "После повторного анализа куратор принял решение не открывать "
            "доступ к активным программам на данном этапе. "
            "Повторный отбор возможен через 3 месяца.",
            parse_mode="HTML",
        )
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.answer("❌ Отправлено override-reject")
    except Exception as e:
        await cb.answer(f"Ошибка: {e}")


# ─── admin helpers ──────────────────────────────────────────────────────────
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    airtable_status = "✅" if AIRTABLE_API_KEY else "⚠️ не задан"
    at_link = f"https://airtable.com/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_ID}"
    await message.answer(
        "🔑 <b>Админ-панель CI Academy</b>\n\n"
        f"<b>Airtable API:</b> {airtable_status}\n"
        f"<b>Курс URL:</b> {COURSE_URL}\n"
        f"<b>WebApp URL:</b> {WEBAPP_URL}\n\n"
        f"📊 <a href='{at_link}'>Таблица кандидатов</a>\n\n"
        "<b>Команды:</b>\n"
        "/admin — эта панель\n"
        "/stats — сколько кандидатов по паттернам\n"
        "/export — скачать CSV со всеми кандидатами\n"
        "/id — твой Telegram id",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@dp.message(Command("id"))
async def cmd_id(message: types.Message):
    await message.answer(f"Твой id: <code>{message.from_user.id}</code>",
                         parse_mode="HTML")


@dp.message(Command("export"))
async def cmd_export(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        data, n = await db_export_csv()
    except Exception as e:
        await message.answer(f"Ошибка экспорта: {e}")
        return
    if n == 0:
        await message.answer("Пока никто не прошёл тест.")
        return
    ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    fname = f"ci_academy_applicants_{ts}.csv"
    await message.answer_document(
        types.BufferedInputFile(data, filename=fname),
        caption=f"📊 Кандидаты: {n} шт.\nФормат: UTF-8 CSV (открывается в Excel).")


@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    stats = await db_stats()
    if stats["total"] == 0:
        await message.answer("Пока никто не прошёл тест.")
        return
    lines = ["📊 <b>Статистика отбора</b>\n",
             f"Всего кандидатов: <b>{stats['total']}</b>",
             f"✅ Принято (2-5): <b>{stats['accepted']}</b>",
             f"❌ Отказано (1): <b>{stats['rejected']}</b>",
             ""]
    for p in (1, 2, 3, 4, 5):
        c = stats["by_pattern"].get(p, 0)
        emoji = {1: "🔴", 2: "🟠", 3: "🔵", 4: "🟢", 5: "⚡"}[p]
        lines.append(f"{emoji} Паттерн {p}: {c}")
    await message.answer("\n".join(lines), parse_mode="HTML")


# ─── main ───────────────────────────────────────────────────────────────────
async def main():
    log.info("Starting CI Academy Bot… (admin=%s, course=%s)", ADMIN_ID, COURSE_URL)
    try:
        await db_init()
    except Exception as e:
        log.error("DB init failed: %s", e)
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
