# 🦄 CI Academy — Telegram Mini App

> Dark Cinematic × Neon Purple × Crypto Unicorn

Система вступительного отбора в криптовалютную академию. 5 психологических тестов → итоговый вердикт одним из 5 паттернов.

---

## 🏗️ Архитектура

```
CIAcademyTGapp/
├── webapp/                    ← GitHub Pages (фронтенд)
│   ├── index.html             ← Welcome + Dashboard прогресса
│   ├── result.html            ← Результаты + Вердикт Академии
│   ├── css/
│   │   └── kryptan.css        ← Дизайн-система (Dark Neon Purple)
│   ├── js/
│   │   └── core.js            ← Прогресс, навигация, TG WebApp API
│   └── tests/
│       ├── holland.html       ← Тест Голланда RIASEC (42 вопроса)
│       ├── gambling.html      ← Склонность к азарту (8 вопросов)
│       ├── hardiness.html     ← Жизнестойкость Мадди (45 вопросов)
│       ├── proforientation.html ← Профориентирование (матрица 6×2)
│       └── tolerance.html     ← Толерантность к неопред. (23 вопроса)
├── bot/
│   └── bot.py                 ← aiogram 3, принимает результаты
├── .github/workflows/
│   └── deploy.yml             ← Auto-deploy на GitHub Pages
├── requirements.txt
└── README.md
```

---

## 🚀 Запуск

### 1. GitHub Pages (WebApp)
1. Пуш в репозиторий → GitHub Actions автоматически деплоит `webapp/` на Pages
2. В настройках репо: **Settings → Pages → Source: GitHub Actions**
3. URL будет: `https://menervatripolska.github.io/CIAcademyTGAps/`

### 2. Telegram Bot — деплой на Railway

1. Получить токен у @BotFather: `/mybots` → выбрать бота → `API Token` → `Revoke current token` (или `/newbot` для нового).
2. Залогиниться на https://railway.app через GitHub.
3. `New Project` → `Deploy from GitHub repo` → выбрать `menervatripolska/CIAcademyTGAps`.
4. В Settings → Variables добавить:
   - `BOT_TOKEN` — новый токен от BotFather
   - `ADMIN_ID` — твой Telegram ID (узнать у @userinfobot)
   - `WEBAPP_URL` — `https://menervatripolska.github.io/CIAcademyTGAps/`
5. Railway подхватит `Procfile` / `railway.json` и поднимет процесс `python bot/bot.py` как worker. Редеплой автоматически при каждом пуше в `main`.

**Локально** (для отладки):
```bash
cp .env.example .env  # заполнить BOT_TOKEN
pip install -r requirements.txt
python bot/bot.py
```

### 3. BotFather настройка
1. `/newapp` → указать URL: `https://menervatripolska.github.io/CIAcademyTGAps/`
2. Или Menu Button: `/setmenubutton` → URL выше

---

## 🧪 Логика тестов

| Тест | Вопросов | Шкала | Что измеряет |
|------|----------|-------|--------------|
| Голланда | 42 пары | R/I/A/S/E/C | Профессиональный тип личности |
| Азарт | 8 | Да/Нет (0–8) | Риск-профиль и импульсивность |
| Жизнестойкость | 45 | 0–3 | Commitment/Control/Challenge |
| Профориентирование | 6 сфер | Интерес × Способности (1–3) | Матрица «Хочу × Могу» |
| Толерантность | 23 | 1–7 | ТН / ИТН / МИТН |

---

## 🏆 5 Паттернов вердикта

| # | Название | Доступ |
|---|----------|--------|
| 1 | АРХИВ | Отказ — критический риск |
| 2 | АНАЛИТИК | Ограниченный — только долгосрочное инвестирование |
| 3 | НАВИГАТОР | Базовый — надёжные активы |
| 4 | ОПЕРАТОР | Полный — активный трейдинг |
| 5 | ЭЛИТА | Приоритет — все инструменты |

---

## 🎨 Дизайн

- **Фон:** `#050508` (почти чёрный)
- **Акцент:** Neon Purple `#9b30ff`
- **Вторичный:** Emerald Green `#00e676`
- **Шрифты:** Orbitron (заголовки) · Rajdhani (UI) · Inter (текст)
- **Стиль:** Dark Cinematic Realism + Crypto Unicorn aesthetic
- **Герои:** Криптан (М) + Криптанша (Ж) — анимированные аватары

---

## 📊 Flow данных

```
Пользователь → TG Bot /start → WebApp открывается
    ↓
5 тестов последовательно (localStorage прогресс)
    ↓
result.html → calcPattern() → Вердикт 1-5
    ↓
tg.sendData(JSON) → Bot получает → Отправляет в ADMIN
    ↓
Админ: [✅ Принять] / [❌ Отказать] → Пользователь уведомлён
```
