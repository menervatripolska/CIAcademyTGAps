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
import hashlib
import hmac
import io
import json
import logging
import os
import sqlite3
import urllib.parse
from datetime import datetime, timezone
from types import SimpleNamespace

import aiohttp
from aiohttp import web
import aiosqlite
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject, CommandStart
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


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                first_seen TEXT,
                last_seen TEXT,
                source_payload TEXT,
                intent TEXT,
                funnel_stage TEXT DEFAULT 'seen',
                last_event_at TEXT,
                course_clicked_at TEXT,
                blocked INTEGER DEFAULT 0
            )
        ''')
        # Backward-compatible migrations for existing Railway/SQLite volumes.
        for col, ddl in {
            "source_payload": "TEXT",
            "intent": "TEXT",
            "funnel_stage": "TEXT DEFAULT 'seen'",
            "last_event_at": "TEXT",
            "course_clicked_at": "TEXT",
        }.items():
            try:
                await db.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e).lower():
                    raise
        await db.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT,
                created_at TEXT NOT NULL
            )
        ''')
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id)")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_stage ON users(funnel_stage)")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_intent ON users(intent)")
        await db.commit()
    log.info("SQLite готова: %s", DB_PATH)


async def db_log_user(user):
    """Логируем каждого кто пишет боту — upsert."""
    if not user or not user.id:
        return
    now = now_iso()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT INTO users (user_id, username, first_name, last_name, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                last_seen=excluded.last_seen,
                blocked=0
        ''', (
            user.id,
            (user.username or "").lstrip("@"),
            user.first_name or "",
            user.last_name or "",
            now, now,
        ))
        await db.commit()


async def db_update_funnel(user_id: int, stage: str | None = None,
                           intent: str | None = None,
                           source_payload: str | None = None,
                           course_clicked: bool = False):
    now = now_iso()
    sets = ["last_event_at=?"]
    vals = [now]
    if stage:
        sets.append("funnel_stage=?")
        vals.append(stage)
    if intent:
        sets.append("intent=?")
        vals.append(intent)
    if source_payload:
        sets.append("source_payload=COALESCE(NULLIF(source_payload, ''), ?)")
        vals.append(source_payload[:240])
    if course_clicked:
        sets.append("course_clicked_at=?")
        vals.append(now)
    vals.append(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE users SET {', '.join(sets)} WHERE user_id=?",
                         vals)
        await db.commit()


async def db_log_event(user_id: int, event_type: str, payload: dict | None = None,
                       stage: str | None = None):
    now = now_iso()
    payload_text = json.dumps(payload or {}, ensure_ascii=False)[:20000]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO events (user_id, event_type, payload, created_at) VALUES (?,?,?,?)",
            (user_id, event_type, payload_text, now),
        )
        if stage:
            await db.execute(
                "UPDATE users SET funnel_stage=?, last_event_at=? WHERE user_id=?",
                (stage, now, user_id),
            )
        else:
            await db.execute(
                "UPDATE users SET last_event_at=? WHERE user_id=?",
                (now, user_id),
            )
        await db.commit()


async def db_mark_blocked(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET blocked=1 WHERE user_id=?", (user_id,))
        await db.commit()


async def db_all_user_ids() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id FROM users WHERE blocked=0 ORDER BY first_seen"
        ) as cur:
            rows = await cur.fetchall()
    return [r[0] for r in rows]


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


async def db_funnel_stats() -> dict:
    stats = {
        "users_total": 0,
        "by_stage": {},
        "by_intent": {},
        "events": {},
        "course_clicked": 0,
    }
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            row = await cur.fetchone()
            stats["users_total"] = row[0] if row else 0
        async with db.execute(
            "SELECT COALESCE(funnel_stage, 'seen'), COUNT(*) FROM users GROUP BY COALESCE(funnel_stage, 'seen')"
        ) as cur:
            async for stage, count in cur:
                stats["by_stage"][stage] = count
        async with db.execute(
            "SELECT COALESCE(intent, 'not_selected'), COUNT(*) FROM users GROUP BY COALESCE(intent, 'not_selected')"
        ) as cur:
            async for intent, count in cur:
                stats["by_intent"][intent] = count
        async with db.execute(
            "SELECT event_type, COUNT(*) FROM events GROUP BY event_type"
        ) as cur:
            async for event_type, count in cur:
                stats["events"][event_type] = count
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE course_clicked_at IS NOT NULL"
        ) as cur:
            row = await cur.fetchone()
            stats["course_clicked"] = row[0] if row else 0
    return stats


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ─── middleware: логируем каждого юзера, кто пишет боту ──────────────────
@dp.update.outer_middleware()
async def user_logger_middleware(handler, event, data):
    try:
        u = None
        msg = getattr(event, 'message', None)
        cb = getattr(event, 'callback_query', None)
        if msg and msg.from_user:
            u = msg.from_user
        elif cb and cb.from_user:
            u = cb.from_user
        if u and not u.is_bot:
            await db_log_user(u)
    except Exception as e:
        log.warning("db_log_user failed: %s", e)
    return await handler(event, data)

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

INTENT_LABELS = {
    "newbie": "Я новичок, хочу понять крипту",
    "chaos": "Уже покупал, но хаос в голове",
    "system": "Хочу DCA/Grid и систему",
    "trading": "Хочу понять, подходит ли трейдинг",
}


def intent_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Новичок: хочу понять крипту", callback_data="intent:newbie")],
        [InlineKeyboardButton(text="Уже покупал, но хаос", callback_data="intent:chaos")],
        [InlineKeyboardButton(text="Хочу DCA/Grid и Crypto OS", callback_data="intent:system")],
        [InlineKeyboardButton(text="Проверить себя для трейдинга", callback_data="intent:trading")],
    ])


def course_keyboard(pattern: int, context: str = "verdict") -> InlineKeyboardMarkup:
    buy_text = "Получить безопасный маршрут" if pattern == 1 else "Забрать курс за $99"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=buy_text,
            callback_data=f"course_open:{pattern}:{context}",
        )],
        [
            InlineKeyboardButton(
                text="Что внутри курса",
                callback_data=f"course_info:{pattern}:{context}",
            ),
            InlineKeyboardButton(
                text="Как оплатить",
                callback_data=f"payment_help:{pattern}:{context}",
            ),
        ],
        [InlineKeyboardButton(
            text="Задать вопрос куратору",
            callback_data=f"ask_curator:{pattern}:{context}",
        )],
    ])


def tracked_course_url(pattern: int, context: str) -> str:
    parsed = urllib.parse.urlparse(COURSE_URL)
    query = urllib.parse.parse_qs(parsed.query)
    query.update({
        "utm_source": ["telegram_bot"],
        "utm_medium": ["funnel"],
        "utm_campaign": [f"pattern_{pattern}"],
        "utm_content": [context],
    })
    return urllib.parse.urlunparse(parsed._replace(
        query=urllib.parse.urlencode(query, doseq=True)
    ))

# ─── /start ─────────────────────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    source_payload = (command.args or "").strip() if command else ""
    await db_update_funnel(message.from_user.id, stage="started",
                           source_payload=source_payload or None)
    await db_log_event(message.from_user.id, "start", {
        "source_payload": source_payload,
    }, stage="started")

    # sendData работает ТОЛЬКО из reply-keyboard — даём большую reply-кнопку.
    kb = ReplyKeyboardMarkup(
        keyboard=[[
            KeyboardButton(
                text="⚡ Открыть диагностику",
                web_app=WebAppInfo(url=WEBAPP_URL),
            )
        ]],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выбери вариант или открой диагностику",
    )
    await message.answer(
        "⚡ <b>CI Academy Selection</b>\n\n"
        "Я помогу понять, какой у тебя сейчас крипто-режим: "
        "безопасный старт, портфель, DCA/Grid или активная торговля.\n\n"
        "Это не скучная анкета и не «экзамен на умного». "
        "На выходе ты получишь:\n\n"
        "• персональный профиль риска\n"
        "• 3 действия на ближайшую неделю\n"
        "• рекомендацию, как заходить в курс «Я — Криптан» и Crypto OS\n\n"
        "Можно пройти быстро за <b>3 минуты</b> или открыть полный профиль "
        "на 15–20 минут.\n\n"
        "Сначала выбери, что ближе всего к твоей ситуации:",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await message.answer(
        "С какой точки стартуем?",
        reply_markup=intent_keyboard(),
    )


@dp.callback_query(F.data.startswith("intent:"))
async def cb_intent(cb: types.CallbackQuery):
    intent = cb.data.split(":", 1)[1]
    label = INTENT_LABELS.get(intent, intent)
    await db_update_funnel(cb.from_user.id, stage="intent_selected",
                           intent=intent)
    await db_log_event(cb.from_user.id, "intent_selected", {
        "intent": intent,
        "label": label,
    }, stage="intent_selected")
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="Открыть диагностику",
            web_app=WebAppInfo(url=WEBAPP_URL),
        )
    ]])
    await cb.message.answer(
        f"Принял: <b>{label}</b>.\n\n"
        "Жми «Открыть диагностику». Быстрый маршрут займёт около 3 минут: "
        "я покажу твой режим, риски и следующий шаг. Если захочешь глубже — "
        "после этого можно пройти полный профиль.",
        parse_mode="HTML",
        reply_markup=kb,
    )
    await cb.answer("Сегмент сохранён")


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
            "Сейчас активная торговля для тебя не самый безопасный маршрут. "
            "Это не отказ от крипты — это рекомендация начать с защиты: "
            "не гнаться за сигналами, не заходить в плечи и собрать простую "
            "систему наблюдения за рынком.\n\n"
            "Твой безопасный старт: база по BTC/ETH/SOL, DCA без эмоций, "
            "лимиты риска и режим «сначала понять систему — потом действовать».",
            parse_mode="HTML",
            reply_markup=course_keyboard(pattern),
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
            "Следующий шаг — посмотреть, что внутри курса и выбрать способ входа.",
            parse_mode="HTML",
            disable_web_page_preview=False,
            reply_markup=course_keyboard(pattern),
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
            "В ближайшие сутки с тобой свяжутся лично, чтобы обсудить детали.",
            parse_mode="HTML",
            disable_web_page_preview=False,
            reply_markup=course_keyboard(pattern),
        )
    else:
        await bot.send_message(
            chat_id,
            "Результаты получены. Куратор свяжется с тобой в ближайшее время.",
        )


async def send_quick_result_to_candidate(chat_id: int, quick: dict, pattern: int):
    title = quick.get("title") or "Твой крипто-режим определён"
    text = quick.get("text") or "Диагностика готова."
    actions = quick.get("actions") or []
    action_lines = "\n".join(f"• {a}" for a in actions[:3])
    if action_lines:
        action_lines = "\n\n<b>Что сделать на этой неделе:</b>\n" + action_lines
    await bot.send_message(
        chat_id,
        "⚡ <b>Быстрая диагностика CI Academy</b>\n\n"
        f"<b>{title}</b>\n\n"
        f"{text}"
        f"{action_lines}\n\n"
        "Если хочешь собрать это в систему, курс «Я — Криптан» ведёт через "
        "8 уроков, Crypto OS, DCA/Grid и практикум через 30 дней.",
        parse_mode="HTML",
        reply_markup=course_keyboard(pattern, "quick_result"),
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


# ─── submission pipeline (общая для sendData и HTTP API) ──────────────────
async def process_submission(user, results: dict, manual_username: str,
                             raw_payload: dict, source: str = "webapp"):
    """user: объект с полями id/username/first_name/last_name.
    Пишет в БД, Airtable, шлёт кандидату и админу. Возвращает dict-результат."""
    await db_log_user(user)
    pattern = int(results.get("pattern") or 0)
    is_quick = raw_payload.get("mode") == "quick" or bool(results.get("quick"))

    verdict = (
        "Quick Lead" if is_quick else
        "Auto-Reject" if pattern == 1 else
        "Priority (P5)" if pattern == 5 else
        "Auto-Accept" if pattern in (2, 3, 4) else
        "Manual Override"
    )
    link_sent = pattern in (2, 3, 4, 5)

    # SQLite
    try:
        await db_insert(user, results, manual_username, pattern,
                        verdict, link_sent, raw_payload)
    except Exception as e:
        log.error("SQLite insert failed: %s", e)

    # Airtable (опционально)
    fields = build_airtable_fields(user, results, manual_username,
                                   pattern, verdict, link_sent, raw_payload)
    airtable_id = None
    try:
        airtable_id = await airtable_create(fields)
    except Exception as e:
        log.error("Airtable write failed: %s", e)

    # Кандидату — персональный вердикт
    try:
        event_type = "quick_result_submitted" if is_quick else "full_result_submitted"
        stage = "quick_result" if is_quick else "full_result"
        await db_log_event(user.id, event_type, {
            "pattern": pattern,
            "verdict": verdict,
            "source": source,
            "link_sent": link_sent,
        }, stage=stage)
        if is_quick:
            await send_quick_result_to_candidate(
                user.id, results.get("quick") or {}, pattern
            )
        else:
            await send_to_candidate(user.id, pattern)
    except Exception as e:
        log.error("Candidate message failed (id=%s): %s", user.id, e)

    # Админу — лог
    try:
        await send_admin_log(user, results, pattern, verdict, airtable_id)
    except Exception as e:
        log.error("Admin log failed: %s", e)

    log.info("Submission processed: user=%s pattern=%s verdict=%s src=%s",
             user.id, pattern, verdict, source)
    return {"ok": True, "pattern": pattern, "verdict": verdict,
            "link_sent": link_sent,
            "course_url": COURSE_URL if link_sent else None}


# ─── Telegram initData validation ────────────────────────────────────────
def verify_init_data(init_data: str) -> dict | None:
    """Проверяет подпись Telegram initData (HMAC-SHA256 по bot_token).
    Возвращает user-dict или None если подпись невалидна/данных нет."""
    if not init_data:
        return None
    try:
        parsed = urllib.parse.parse_qs(init_data, strict_parsing=True,
                                       keep_blank_values=True)
    except Exception:
        return None
    pairs = {k: v[0] for k, v in parsed.items()}
    recv_hash = pairs.pop("hash", None)
    if not recv_hash:
        return None
    data_check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs.keys()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(),
                          hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check.encode(),
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, recv_hash):
        log.warning("initData hash mismatch")
        return None
    user_raw = pairs.get("user")
    if not user_raw:
        return None
    try:
        return json.loads(user_raw)
    except Exception:
        return None


# ─── HTTP API (aiohttp) ───────────────────────────────────────────────────
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS, GET",
    "Access-Control-Allow-Headers": "Content-Type, X-Telegram-Init-Data",
}


async def http_submit(request: web.Request) -> web.Response:
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    u = verify_init_data(init_data)
    if not u:
        return web.json_response({"ok": False, "error": "bad_init_data"},
                                 status=401, headers=CORS_HEADERS)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad_json"},
                                 status=400, headers=CORS_HEADERS)

    results = payload.get("results", {}) or {}
    manual_username = (payload.get("manual_username") or "").strip().lstrip("@")

    user = SimpleNamespace(
        id=int(u.get("id")),
        username=u.get("username") or "",
        first_name=u.get("first_name") or "",
        last_name=u.get("last_name") or "",
    )
    result = await process_submission(user, results, manual_username,
                                      payload, source="http")
    return web.json_response(result, headers=CORS_HEADERS)


async def http_options(request: web.Request) -> web.Response:
    return web.Response(status=204, headers=CORS_HEADERS)


async def http_health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "ci-academy-bot"},
                             headers=CORS_HEADERS)


def build_web_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/api/submit", http_submit)
    app.router.add_options("/api/submit", http_options)
    app.router.add_get("/health", http_health)
    app.router.add_get("/", http_health)
    return app


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
    manual_username = (payload.get("manual_username") or "").strip().lstrip("@")

    try:
        await message.answer(
            "✅ Результаты получены. Секунду — формируем вердикт…",
            reply_markup=ReplyKeyboardRemove(),
        )
    except Exception:
        pass

    await process_submission(user, results, manual_username, payload,
                             source="sendData")


# ─── funnel CTA callbacks ──────────────────────────────────────────────────
@dp.callback_query(F.data.startswith("course_open:"))
async def cb_course_open(cb: types.CallbackQuery):
    _, pattern_raw, context = cb.data.split(":", 2)
    pattern = int(pattern_raw)
    await db_update_funnel(cb.from_user.id, stage="course_clicked",
                           course_clicked=True)
    await db_log_event(cb.from_user.id, "course_clicked", {
        "pattern": pattern,
        "context": context,
    }, stage="course_clicked")
    url = tracked_course_url(pattern, context)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Открыть ciacademy.kz", url=url)
    ]])
    if pattern == 1:
        text = (
            "Я открою страницу курса, но твой маршрут — не агрессивный трейдинг. "
            "Смотри блоки про базу рынка, DCA, риск и Crypto OS как систему "
            "наблюдения без эмоций."
        )
    else:
        text = (
            "Отлично. Ниже ссылка на курс «Я — Криптан»: 8 уроков, Crypto OS, "
            "DCA/Grid, AI-ассистент и финальный практикум."
        )
    await cb.message.answer(text, reply_markup=kb)
    await cb.answer("Клик записан")


@dp.callback_query(F.data.startswith("course_info:"))
async def cb_course_info(cb: types.CallbackQuery):
    _, pattern_raw, context = cb.data.split(":", 2)
    pattern = int(pattern_raw)
    await db_log_event(cb.from_user.id, "course_info_viewed", {
        "pattern": pattern,
        "context": context,
    }, stage="course_info_viewed")
    await cb.message.answer(
        "📦 <b>Что внутри «Я — Криптан»</b>\n\n"
        "• 8 уроков: от базы денег/BTC/ETH/SOL до портфеля, риска и операционки\n"
        "• Crypto OS: макро-режим, DCA-движок, Grid-стратегии, watchlist\n"
        "• AI-ассистент Нова и чек-листы решений без эмоций\n"
        "• Через 30 дней — 2-часовой практикум в Google Meet\n"
        "• Цена первой волны: $99 ≈ 46 000 ₸",
        parse_mode="HTML",
        reply_markup=course_keyboard(pattern, "course_info"),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("payment_help:"))
async def cb_payment_help(cb: types.CallbackQuery):
    _, pattern_raw, context = cb.data.split(":", 2)
    pattern = int(pattern_raw)
    await db_log_event(cb.from_user.id, "payment_help_viewed", {
        "pattern": pattern,
        "context": context,
    }, stage="payment_help_viewed")
    await cb.message.answer(
        "💳 <b>Оплата</b>\n\n"
        "На сайте доступны варианты под KZ/RU/международные карты: "
        "карта, Каспи/рассрочка и USDT/BTC. После оплаты доступ открывается "
        "мгновенно.\n\n"
        "Если что-то не проходит — нажми «Задать вопрос куратору», и я отмечу "
        "тебя для ручной помощи.",
        parse_mode="HTML",
        reply_markup=course_keyboard(pattern, "payment_help"),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("ask_curator:"))
async def cb_ask_curator(cb: types.CallbackQuery):
    _, pattern_raw, context = cb.data.split(":", 2)
    pattern = int(pattern_raw)
    await db_log_event(cb.from_user.id, "asked_curator", {
        "pattern": pattern,
        "context": context,
    }, stage="asked_question")
    uname = f"@{cb.from_user.username}" if cb.from_user.username else "(нет @username)"
    name = " ".join(filter(None, [
        cb.from_user.first_name,
        cb.from_user.last_name,
    ])) or "—"
    await bot.send_message(
        ADMIN_ID,
        "💬 <b>Вопрос куратору</b>\n\n"
        f"Пользователь: {name} {uname}\n"
        f"TG ID: <code>{cb.from_user.id}</code>\n"
        f"Паттерн: {pattern}\n"
        f"Контекст: {context}\n\n"
        "Напиши ему вручную или ответь через личку.",
        parse_mode="HTML",
    )
    await cb.message.answer(
        "Я отметил тебя для куратора. Напиши сюда одним сообщением, что именно "
        "хочешь уточнить: оплата, программа, подходит ли курс, стартовый капитал "
        "или Crypto OS."
    )
    await cb.answer("Куратор увидит запрос")


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
        "/funnel — статусы воронки и клики\n"
        "/export — скачать CSV со всеми кандидатами\n"
        "/broadcast — рассылка всем подписчикам (reply на сообщение)\n"
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


@dp.message(Command("funnel"))
async def cmd_funnel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    stats = await db_funnel_stats()
    lines = [
        "🧭 <b>Воронка CI Academy</b>\n",
        f"Всего пользователей в базе: <b>{stats['users_total']}</b>",
        f"Кликнули курс: <b>{stats['course_clicked']}</b>",
        "",
        "<b>По стадиям:</b>",
    ]
    stage_names = {
        "seen": "увиден ботом",
        "started": "нажал /start",
        "intent_selected": "выбрал интерес",
        "quick_result": "получил быстрый результат",
        "full_result": "отправил полный результат",
        "course_info_viewed": "смотрел состав курса",
        "payment_help_viewed": "смотрел оплату",
        "course_clicked": "открыл ссылку курса",
        "asked_question": "попросил куратора",
    }
    for stage, count in sorted(stats["by_stage"].items()):
        lines.append(f"• {stage_names.get(stage, stage)}: <b>{count}</b>")

    lines.append("\n<b>По интересу:</b>")
    for intent, count in sorted(stats["by_intent"].items()):
        label = INTENT_LABELS.get(intent, "Не выбрано" if intent == "not_selected" else intent)
        lines.append(f"• {label}: <b>{count}</b>")

    if stats["events"]:
        lines.append("\n<b>События:</b>")
        for event_type, count in sorted(stats["events"].items()):
            lines.append(f"• {event_type}: <b>{count}</b>")

    await message.answer("\n".join(lines), parse_mode="HTML")


# ─── broadcast (/broadcast reply-на-сообщение → шлём всем) ────────────
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

_pending_broadcast: dict[int, int] = {}  # admin_id → msg_id ожидающий подтверждения


@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    if not message.reply_to_message:
        await message.answer(
            "📣 <b>Как разослать сообщение всем подписчикам бота:</b>\n\n"
            "1. Напиши в этот чат нужное сообщение (можно с фото/видео).\n"
            "2. Ответь на это сообщение командой <code>/broadcast</code>.\n"
            "3. Бот покажет сколько людей в базе и попросит подтвердить.\n\n"
            "💡 Ссылку на курс просто включи в текст: "
            f"<code>{COURSE_URL}</code>",
            parse_mode="HTML",
        )
        return

    user_ids = await db_all_user_ids()
    n = len(user_ids)
    if n == 0:
        await message.answer("В базе пока нет подписчиков.")
        return

    _pending_broadcast[message.from_user.id] = message.reply_to_message.message_id
    kb = types.InlineKeyboardMarkup(inline_keyboard=[[
        types.InlineKeyboardButton(
            text=f"📨 Да, разослать {n} людям",
            callback_data=f"bcast_go:{message.reply_to_message.message_id}"
        ),
        types.InlineKeyboardButton(
            text="❌ Отмена", callback_data="bcast_cancel"
        ),
    ]])
    await message.answer(
        f"Разослать это сообщение <b>{n}</b> подписчикам?\n\n"
        f"Сообщение будет скопировано 1-в-1 (текст + медиа).\n"
        f"Отправка займёт ~{max(1, n // 25)} сек.",
        parse_mode="HTML",
        reply_markup=kb,
    )


@dp.callback_query(F.data == "bcast_cancel")
async def cb_bcast_cancel(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        return
    _pending_broadcast.pop(cb.from_user.id, None)
    await cb.message.edit_text("❌ Рассылка отменена.")
    await cb.answer()


@dp.callback_query(F.data.startswith("bcast_go:"))
async def cb_bcast_go(cb: types.CallbackQuery):
    if cb.from_user.id != ADMIN_ID:
        await cb.answer("Нет доступа", show_alert=True)
        return
    src_msg_id = int(cb.data.split(":", 1)[1])
    user_ids = await db_all_user_ids()
    total = len(user_ids)
    await cb.message.edit_text(f"📨 Рассылаю {total} подписчикам…")
    await cb.answer()

    sent, failed, blocked = 0, 0, 0
    for i, uid in enumerate(user_ids, 1):
        try:
            await bot.copy_message(
                chat_id=uid,
                from_chat_id=cb.message.chat.id,
                message_id=src_msg_id,
            )
            sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await bot.copy_message(chat_id=uid,
                                       from_chat_id=cb.message.chat.id,
                                       message_id=src_msg_id)
                sent += 1
            except Exception as e2:
                log.warning("broadcast retry fail %s: %s", uid, e2)
                failed += 1
        except TelegramForbiddenError:
            blocked += 1
            try:
                await db_mark_blocked(uid)
            except Exception:
                pass
        except Exception as e:
            log.warning("broadcast fail uid=%s: %s", uid, e)
            failed += 1
        # throttle: ~25 msg/sec — ниже лимита Telegram 30/sec
        await asyncio.sleep(0.04)
        # прогресс каждые 50
        if i % 50 == 0:
            try:
                await cb.message.edit_text(
                    f"📨 Рассылаю… {i}/{total}\n"
                    f"✅ {sent} | 🚫 заблок: {blocked} | ⚠️ ошибки: {failed}"
                )
            except Exception:
                pass

    _pending_broadcast.pop(cb.from_user.id, None)
    await cb.message.edit_text(
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"Всего: {total}\n"
        f"Доставлено: <b>{sent}</b>\n"
        f"Заблокировали бота: {blocked}\n"
        f"Ошибки: {failed}",
        parse_mode="HTML",
    )


# ─── main ───────────────────────────────────────────────────────────────────
async def main():
    log.info("Starting CI Academy Bot… (admin=%s, course=%s)", ADMIN_ID, COURSE_URL)
    try:
        await db_init()
    except Exception as e:
        log.error("DB init failed: %s", e)

    # HTTP API — для Mini App, которая не может sendData (Menu Button / прямая ссылка).
    port = int(os.getenv("PORT", "8080"))
    app = build_web_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("HTTP API запущен на 0.0.0.0:%s", port)

    try:
        await dp.start_polling(bot, skip_updates=True)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
