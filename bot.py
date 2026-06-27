import json
import logging
import os
import re
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters, ConversationHandler
)

# ─────────────────────────────────────────────
#  Logging
# ─────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s │ %(levelname)s │ %(name)s │ %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  Env
# ─────────────────────────────────────────────
BOT_TOKEN     = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
OWNER_ID      = int(os.getenv("OWNER_ID", "0"))
SISTER_ID     = int(os.getenv("SISTER_ID", "0"))
ANTHROPIC_KEY = os.getenv("GROQ_API_KEY", "")

DATA_DIR    = Path(os.getenv("DATA_DIR", "."))
DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = DATA_DIR / "config.json"

# Жестко задаем часовой пояс для всех расчетов
TZ = ZoneInfo("Europe/Kiev")

# ─────────────────────────────────────────────
#  Праздники (MM-DD формат)
# ─────────────────────────────────────────────
HOLIDAYS = {
    "01-01": ("🎄 С Новым годом!", "Пусть этот год принесёт тебе только радость, любовь и незабываемые моменты. Ты лучшая! 🥂✨"),
    "01-07": ("🎄 С Рождеством Христовым!", "Пусть Рождество наполнит твой дом теплом, а сердце — любовью. Ты — моё лучшее чудо! 🌟"),
    "02-14": ("💝 С Днём святого Валентина!", "Ты — моя самая большая любовь. Каждый день с тобой — как первый день влюблённости. Спасибо, что ты есть! 💕"),
    "03-08": ("🌸 С 8 Марта!", "Сегодня твой день, моя лучшая девочка. Ты — цветок, который украшает мою жизнь каждый день. Люблю тебя безгранично! 🌹"),
    "04-01": ("😄 С Днём смеха!", "Ты сама по себе — лучшая шутка судьбы, которую она с нами сыграла. Только это шутка со счастливым концом! 😂💛"),
    "05-01": ("🌿 С Первомаем!", "Пусть весна принесёт нам новые мечты и яркие моменты вместе. Ты — моя весна каждый день! 🌼"),
    "06-01": ("👶 С Днём защиты детей!", "В тебе есть что-то по-детски чистое и искреннее — и именно за это я тебя обожаю! 🌈"),
    "08-24": ("🇺🇦 С Днём независимости Украины!", "Горжусь тобой и нашей страной. Ты — моё личное независимое государство счастья! 💛💙"),
    "09-01": ("📚 С началом сентября!", "Новый сезон, новые возможности — и ты рядом. Это уже делает любой день идеальным! 🍂"),
    "10-31": ("🎃 Хэллоуин!", "Ты — самое страшное, что со мной случилось, потому что я не могу без тебя жить! 👻😈"),
    "12-19": ("🎅 С Днём Николая!", "Святой Николай приносит подарки только хорошим людям. Тебе — целый мешок, потому что ты лучшая! 🎁"),
    "12-25": ("🎄 С Рождеством!", "Пусть этот праздник принесёт мир, любовь и уют. Ты — лучший подарок в моей жизни! ⭐"),
    "12-31": ("🎆 С Новым годом, любимая!", "Год заканчивается, но моя любовь к тебе только растёт. С нетерпением жду нового года — вместе с тобой! 🥂💫"),
}

# Пул ежедневных сообщений (от брата сестре)
DAILY_MESSAGES_POOL = [
    "Ты красавица и умница — и это не просто слова. Ты доказываешь это каждый день. Так держать! 💛",
    "Знаешь, иметь такую сестру — это подарок. Ты всегда находишь способ сделать всё вокруг лучше. Горжусь тобой! 🌟",
    "Ты сегодня точно справишься со всем, что задумала. Я в тебя верю — и это на 100%. 💪",
    "Напоминаю тебе официально: ты потрясающая. Можешь сохранить это сообщение и перечитывать при необходимости. 😄💛",
    "Ты умеешь делать жизнь вокруг теплее — просто своим присутствием. Это редкий талант, цени его. 🌸",
    "Сегодня хочу сказать: ты молодец. Не за что-то конкретное — просто потому что ты есть. ❤️",
    "Ты красивая, умная и добрая. Три в одном — это редкость. Берегу тебя как сокровище. 💎",
    "Просто хотел напомнить, что у тебя всё получится. Всегда. Потому что ты — ты. 🚀",
    "Если бы выбирали сестёр как лучших друзей — я бы выбрал тебя снова. Без раздумий. 🤝💛",
    "Ты умница. Каждый день. Даже когда сама этого не замечаешь. Замечаю я. 👀✨",
    "Знаешь что мне в тебе нравится? Всё. Но особенно — то, как ты не сдаёшься. 💥",
    "Сегодня ты точно красавица. Да и вчера тоже была. И завтра будешь. Это просто факт. 😊",
    "Ты — человек, который делает мою жизнь лучше. Спасибо что ты есть, сестрёнка. 🌈",
    "Напоминание дня: ты справляешься лучше, чем думаешь. Продолжай в том же духе! 🔥",
    "Горжусь тобой тихо, но постоянно. Сегодня решил сказать это вслух. Точнее, написать. 💬💛",
    "Ты — лучшая версия себя каждый день. И это впечатляет. Правда. 🌿",
    "Просто так: ты классная. Сохрани, пригодится в трудный момент. 📌",
    "Ты умеешь быть сильной когда надо и мягкой когда нужно. Это мудрость. Уважаю. 🦋",
    "Если бы у всех была такая сестра — мир был бы намного добрее. Мне повезло. 🍀",
    "Сегодня ты снова молодец. Вчера тоже была. Завтра тоже будешь. Это традиция. 📅💛",
    "Ты — человек, на которого можно положиться. И это дорогого стоит. Ценю тебя. 🤗",
    "Напоминаю: ты справляешься. Даже когда кажется что нет — справляешься. Я вижу. 👁️✨",
    "Ты делаешь мир лучше — просто тем, что в нём есть. Это не преувеличение. 🌍💛",
    "Хочу чтобы ты знала: ты классная. Не потому что я обязан так говорить — а потому что это правда. 💯",
    "Сегодня ты точно справишься. И выглядишь при этом прекрасно — я уверен. 😎🌸",
    "Ты умная, смелая и красивая. Можешь распечатать и повесить на холодильник. 📄💛",
    "Если я когда-нибудь сомневался в тебе — это была моя ошибка. Ты всегда всё делаешь правильно. 🙌",
    "Ты — моя любимая сестра. Единственная, кстати. Но даже если бы было много — ты всё равно была бы первой. 😄❤️",
    "Сегодня просто хочу сказать: молодец. Так держать. Я горжусь. Всё. 🏆",
    "Ты красавица и умница — и это я говорю не потому что положено, а потому что это чистая правда. 💛✨",
]

# ─────────────────────────────────────────────
#  ConversationHandler states
# ─────────────────────────────────────────────
(WAITING_COUNTER_NAME, WAITING_COUNTER_DEADLINE,
 WAITING_DELETE_CONFIRM, WAITING_NEW_DEADLINE,
 WAITING_LOVE_DATE, WAITING_LOVE_TIME) = range(6)

# ─────────────────────────────────────────────
#  Default config
# ─────────────────────────────────────────────
DEFAULT_CONFIG = {
    "counters": {
        "light": {"name": "Свет 💡", "deadline_day": 30, "done": False, "last_month": None},
        "water": {"name": "Вода 💧", "deadline_day": 20, "done": False, "last_month": None},
    },
    "default_schedule": {
        "5": ["09:00"],
        "2": ["09:00", "20:00"],
        "0": ["09:00", "13:00", "17:00", "20:00"],
    },
    "sister": {"chat_id": SISTER_ID},
    # Модуль ежедневных любовных сообщений
    "love": {
        "enabled": False,
        "start_date": None,      # "YYYY-MM-DD"
        "send_time": "09:00",    # когда отправлять
        "msg_index": 0,          # какое сообщение из пула следующее
    },
}

# ─────────────────────────────────────────────
#  Config helpers
# ─────────────────────────────────────────────
def load_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        # Merge nested love defaults
        for k, v in DEFAULT_CONFIG["love"].items():
            cfg["love"].setdefault(k, v)
        return cfg
    return json.loads(json.dumps(DEFAULT_CONFIG))

def save_config(cfg: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

cfg = load_config()

# ─────────────────────────────────────────────
#  Helpers — счётчики
# ─────────────────────────────────────────────
def current_month() -> str:
    return datetime.now(TZ).strftime("%Y-%m")

def reset_if_new_month():
    month = current_month()
    changed = False
    for c in cfg["counters"].values():
        if c.get("done") and c.get("last_month") != month:
            c["done"] = False
            c["last_month"] = None
            changed = True
    if changed:
        save_config(cfg)
        logger.info("Monthly reset done.")

def mark_done(key: str):
    cfg["counters"][key]["done"] = True
    cfg["counters"][key]["last_month"] = current_month()
    save_config(cfg)

def status_text() -> str:
    reset_if_new_month()
    month = datetime.now(TZ).strftime("%m.%Y")
    lines = [f"📊 *Счётчики — {month}*\n"]
    for key, c in cfg["counters"].items():
        icon = "✅" if c["done"] else "❌"
        lines.append(f"{icon} {c['name']} — дедлайн *{c['deadline_day']}-е*")
    return "\n".join(lines)

def main_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for key, c in cfg["counters"].items():
        if not c["done"]:
            buttons.append([InlineKeyboardButton(
                f"✅ {c['name']} — отправил", callback_data=f"done_{key}"
            )])
    buttons.append([InlineKeyboardButton("📋 Обновить статус", callback_data="status")])
    return InlineKeyboardMarkup(buttons)

def counters_list_keyboard(action: str) -> InlineKeyboardMarkup:
    buttons = []
    for key, c in cfg["counters"].items():
        buttons.append([InlineKeyboardButton(
            f"{c['name']} (дедлайн {c['deadline_day']}-е)", callback_data=f"{action}_{key}"
        )])
    buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(buttons)

def get_due_soon(days_threshold: int = 5) -> dict:
    today = datetime.now(TZ).day
    result = {}
    for key, c in cfg["counters"].items():
        if c["done"]:
            continue
        if c["deadline_day"] - today <= days_threshold:
            result[key] = c
    return result

# ─────────────────────────────────────────────
#  Helpers — любовные сообщения
# ─────────────────────────────────────────────
def days_since_start() -> int | None:
    start = cfg["love"].get("start_date")
    if not start:
        return None
    try:
        d0 = date.fromisoformat(start)
        return (date.today() - d0).days + 1
    except ValueError:
        return None

def today_holiday() -> tuple[str, str] | None:
    key = datetime.now(TZ).strftime("%m-%d")
    return HOLIDAYS.get(key)

async def generate_love_message(day_num: int, bot) -> str:
    """Генерирует сообщение через Groq API или берёт из пула."""
    holiday = today_holiday()
    if holiday:
        title, body = holiday
        return f"{title}\n\nЭто уже *{day_num}* день вместе 🥰\n\n{body}"

    # Новый промт для Groq
    system_prompt = (
        "Ты — старший брат, который пишет своей младшей сестре тёплые сообщения с чёрным юмором.\n\n"
        "Стиль:\n"
        "- Братская любовь, поддержка, дерзкое подтрунивание и чёрный юмор.\n"
        "- Обязательно ярко и творчески обыгрывай номер дня (сегодня уже N-й день) — это важная часть сообщения.\n"
        "- Говори, что она красавица и умница, но через братский троллинг и любовь.\n"
        "- Сообщения должны быть чуть длиннее — 3–4 предложения.\n"
        "- Живой, разговорный русский.\n"
        "- Добавляй эмодзи в меру.\n"
        "- Выдавай ТОЛЬКО текст самого сообщения, без кавычек и пояснений."
    )

    user_prompt = f"Сегодня {day_num}-й день. Напиши сообщение сестре."

    try:
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {ANTHROPIC_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.3-70b-versatile",
                    "max_tokens": 400,
                    "temperature": 0.85,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ]
                }
            )
        
        data = resp.json()
        text = data["choices"][0]["message"]["content"].strip()
        
        if text and len(text) > 20:  # минимальная защита от пустого ответа
            return text

    except Exception as e:
        logger.warning(f"Groq API error: {e}")

    # Fallback — пул сообщений
    idx = cfg["love"]["msg_index"] % len(DAILY_MESSAGES_POOL)
    msg = DAILY_MESSAGES_POOL[idx]
    cfg["love"]["msg_index"] = idx + 1
    save_config(cfg)
    
    return f"День *{day_num}* 🌟\n\n{msg}"

# ─────────────────────────────────────────────
#  Scheduler
# ─────────────────────────────────────────────
scheduler = AsyncIOScheduler(timezone=TZ)

async def notify_sister(bot, keys: list[str]):
    sister_id = cfg["sister"].get("chat_id", 0)
    if not sister_id or not keys:
        return
    names = ", ".join(cfg["counters"][k]["name"] for k in keys if k in cfg["counters"])
    try:
        await bot.send_message(
            chat_id=sister_id,
            text=(
                f"Привет! 👋\n\n"
                f"Пришли, пожалуйста, *фото показаний*:\n"
                f"*{names}*\n\n"
                f"Просто отправь фото сюда — они придут автоматически 📸"
            ),
            parse_mode="Markdown"
        )
        logger.info(f"Sister notified: {keys}")
    except Exception as e:
        logger.warning(f"Sister notify error: {e}")

async def send_reminder(app: Application, counter_key: str):
    reset_if_new_month()
    c = cfg["counters"].get(counter_key)
    if not c or c["done"]:
        return

    today = datetime.now(TZ).day
    deadline = c["deadline_day"]
    days_left = deadline - today

    if days_left > 0:
        urgency = f"⏰ До дедлайна *{days_left} дн.*"
    elif days_left == 0:
        urgency = "🚨 *Сегодня последний день!*"
    else:
        urgency = f"🔴 *Просрочено на {abs(days_left)} дн.!*"

    buttons = [[InlineKeyboardButton(f"✅ {c['name']} — отправил", callback_data=f"done_{counter_key}")]]
    if cfg["sister"].get("chat_id", 0):
        buttons.append([InlineKeyboardButton(
            f"📨 Напомнить сестре про {c['name']}",
            callback_data=f"ping_sister_{counter_key}"
        )])

    await app.bot.send_message(
        chat_id=OWNER_ID,
        text=f"📟 Напоминание: *{c['name']}*\n\n{urgency}\n\nНажми когда отправишь 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

    # Пишем сестре при каждом напоминании начиная с 5 дней до дедлайна
    if days_left <= 5 and cfg["sister"].get("chat_id", 0):
        await notify_sister(app.bot, [counter_key])

async def send_daily_love(app: Application):
    """Ежедневное сообщение сестре (сразу для копирования)."""
    love = cfg.get("love", {})
    if not love.get("enabled") or not love.get("start_date"):
        return

    day_num = days_since_start()
    if day_num is None or day_num < 1:
        return

    text = await generate_love_message(day_num, app.bot)
    
    # Очищаем от спецсимволов HTML и звездочек Markdown
    clean_text = re.sub(r"[<>&*]", "", text)

    # Отправляем текст без кнопок внутри тега <code>
    await app.bot.send_message(
        chat_id=OWNER_ID,
        text=f"<code>{clean_text}</code>",
        parse_mode="HTML"
    )

    cfg["love"]["last_text"] = text
    save_config(cfg)


async def cmd_love_test(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    
    day_num = days_since_start() or 1
    text = await generate_love_message(day_num, ctx.bot)
    
    # Очищаем от спецсимволов HTML и звездочек Markdown
    clean_text = re.sub(r"[<>&*]", "", text)
    
    cfg["love"]["last_text"] = text
    save_config(cfg)
    
    await update.message.reply_text(
        f"<code>{clean_text}</code>", 
        parse_mode="HTML"
    )

def rebuild_schedule(app: Application):
    for job in scheduler.get_jobs():
        if job.id.startswith("rem_") or job.id == "daily_love" or job.id == "monthly_reset":
            job.remove()

    sched = cfg.get("default_schedule", DEFAULT_CONFIG["default_schedule"])

    # Напоминания о счётчиках
    for key, c in cfg["counters"].items():
        deadline = c["deadline_day"]
        for days_before_str, times in sched.items():
            days_before = int(days_before_str)
            send_day = max(1, deadline - days_before)
            for t in times:
                hour, minute = map(int, t.split(":"))
                job_id = f"rem_{key}_{days_before}_{t.replace(':','')}"
                scheduler.add_job(
                    send_reminder,
                    CronTrigger(day=send_day, hour=hour, minute=minute),
                    args=[app, key],
                    id=job_id,
                    replace_existing=True,
                )

    # Ежедневное любовное сообщение
    love = cfg.get("love", {})
    if love.get("enabled") and love.get("send_time"):
        h, m = map(int, love["send_time"].split(":"))
        scheduler.add_job(
            send_daily_love,
            CronTrigger(hour=h, minute=m),
            args=[app],
            id="daily_love",
            replace_existing=True,
        )
        logger.info(f"Daily love scheduled at {love['send_time']}")

    scheduler.add_job(
        reset_if_new_month,
        CronTrigger(day=1, hour=0, minute=1),
        id="monthly_reset",
        replace_existing=True,
    )
    logger.info(f"Schedule rebuilt: {len(scheduler.get_jobs())} jobs.")

# ─────────────────────────────────────────────
#  /start
# ─────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    name = update.effective_user.first_name
    if uid != OWNER_ID:
        await update.message.reply_text(
            f"Привет, {name}! 👋\n\nТвой chat\\_id: `{uid}`\nПередай его владельцу бота.",
            parse_mode="Markdown"
        )
        return
    await update.message.reply_text(
        "👋 *Бот напоминаний*\n\n"
        "*Счётчики:*\n"
        "├ /status — статус\n"
        "├ /add — добавить счётчик\n"
        "├ /delete — удалить\n"
        "├ /deadline — изменить дедлайн\n"
        "├ /remind — тест напоминания\n"
        "└ /sister — написать сестре\n\n"
        "*Сообщения сестре:*\n"
        "├ /love — настройки\n"
        "├ /love\\_date — изменить дату отсчёта\n"
        "├ /love\\_test — тест сообщения\n"
        "└ /love\\_off — выключить\n\n"
        "*Прочее:*\n"
        "└ /settings — расписание напоминаний",
        parse_mode="Markdown"
    )

# ─────────────────────────────────────────────
#  Счётчики — команды
# ─────────────────────────────────────────────
async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    await update.message.reply_text(status_text(), parse_mode="Markdown", reply_markup=main_keyboard())

async def cmd_remind(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    for key in cfg["counters"]:
        await send_reminder(ctx.application, key)

async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return ConversationHandler.END
    await update.message.reply_text(
        "➕ *Новый счётчик*\n\nВведи название (например: `Газ 🔥`):",
        parse_mode="Markdown"
    )
    return WAITING_COUNTER_NAME

async def add_get_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_counter_name"] = update.message.text.strip()
    await update.message.reply_text(
        f"📅 Название: *{ctx.user_data['new_counter_name']}*\n\nВведи дедлайн (число месяца 1–28):",
        parse_mode="Markdown"
    )
    return WAITING_COUNTER_DEADLINE

async def add_get_deadline(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        day = int(update.message.text.strip())
        assert 1 <= day <= 28
    except (ValueError, AssertionError):
        await update.message.reply_text("❌ Введи число от 1 до 28:")
        return WAITING_COUNTER_DEADLINE
    name = ctx.user_data["new_counter_name"]
    key = re.sub(r"[^\w]", "_", name.lower())[:20] or f"c{len(cfg['counters'])+1}"
    cfg["counters"][key] = {"name": name, "deadline_day": day, "done": False, "last_month": None}
    save_config(cfg)
    rebuild_schedule(ctx.application)
    await update.message.reply_text(f"✅ Добавлен: *{name}* — дедлайн *{day}-е*.", parse_mode="Markdown")
    return ConversationHandler.END

async def add_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Отменено.")
    return ConversationHandler.END

async def cmd_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not cfg["counters"]:
        await update.message.reply_text("Нет счётчиков.")
        return
    await update.message.reply_text(
        "🗑 *Какой счётчик удалить?*", parse_mode="Markdown",
        reply_markup=counters_list_keyboard("del")
    )

async def cmd_deadline(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return ConversationHandler.END
    if not cfg["counters"]:
        await update.message.reply_text("Нет счётчиков.")
        return ConversationHandler.END
    await update.message.reply_text(
        "📅 *Для какого счётчика изменить дедлайн?*", parse_mode="Markdown",
        reply_markup=counters_list_keyboard("setd")
    )
    return WAITING_NEW_DEADLINE

async def deadline_get_day(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        day = int(update.message.text.strip())
        assert 1 <= day <= 28
    except (ValueError, AssertionError):
        await update.message.reply_text("❌ Введи число от 1 до 28:")
        return WAITING_NEW_DEADLINE
    key = ctx.user_data.get("deadline_key")
    if key and key in cfg["counters"]:
        cfg["counters"][key]["deadline_day"] = day
        save_config(cfg)
        rebuild_schedule(ctx.application)
        await update.message.reply_text(
            f"✅ *{cfg['counters'][key]['name']}* — дедлайн *{day}-е*.", parse_mode="Markdown"
        )
    return ConversationHandler.END

async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    sched = cfg.get("default_schedule", DEFAULT_CONFIG["default_schedule"])
    lines = []
    for days, times in sorted(sched.items(), key=lambda x: -int(x[0])):
        d = int(days)
        label = f"За {d} дн." if d > 0 else "В день дедлайна"
        lines.append(f"• {label}: {', '.join(times)}")
    love = cfg.get("love", {})
    love_status = (
        f"✅ Включены — с {love.get('start_date', '?')}, в {love.get('send_time', '?')}"
        if love.get("enabled") else "❌ Выключены"
    )
    await update.message.reply_text(
        "⚙️ *Настройки*\n\n"
        "*Расписание счётчиков:*\n" + "\n".join(lines) + "\n\n"
        f"*Любовные сообщения:* {love_status}\n\n"
        "`/set_times 2 09:00 20:00` — изменить расписание\n"
        "`/love` — настроить сообщения",
        parse_mode="Markdown"
    )

async def cmd_set_times(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    try:
        days_before = int(ctx.args[0])
        times = ctx.args[1:]
        assert times
        for t in times:
            h, m = map(int, t.split(":"))
            assert 0 <= h <= 23 and 0 <= m <= 59
    except Exception:
        await update.message.reply_text("❌ Использование: `/set_times 2 09:00 20:00`", parse_mode="Markdown")
        return
    cfg.setdefault("default_schedule", {})[str(days_before)] = times
    save_config(cfg)
    rebuild_schedule(ctx.application)
    await update.message.reply_text(f"✅ За *{days_before}* дн.: {', '.join(times)}", parse_mode="Markdown")

# ─────────────────────────────────────────────
#  /sister
# ─────────────────────────────────────────────
async def cmd_sister(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    sister_id = cfg["sister"].get("chat_id", 0)
    if not sister_id:
        await update.message.reply_text(
            "❌ chat\\_id сестры не задан.\n\nПопроси её написать `/start` боту.",
            parse_mode="Markdown"
        )
        return
    due = get_due_soon(days_threshold=5)
    if not due:
        all_pending = {k: c for k, c in cfg["counters"].items() if not c["done"]}
        if not all_pending:
            await update.message.reply_text("✅ Все показания уже отправлены!")
        else:
            names_later = ", ".join(c["name"] for c in all_pending.values())
            await update.message.reply_text(
                f"⏳ До дедлайна ещё больше 5 дней.\n\n"
                f"Счётчики: *{names_later}*\n\nВсё равно написать сестре?",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📨 Написать всё равно", callback_data="sister_force_all")
                ]])
            )
        return
    names = ", ".join(c["name"] for c in due.values())
    await notify_sister(ctx.bot, list(due.keys()))
    await update.message.reply_text(f"✅ Написал сестре насчёт: *{names}*", parse_mode="Markdown")

# ─────────────────────────────────────────────
#  Фото от сестры
# ─────────────────────────────────────────────
async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    sister_id = cfg["sister"].get("chat_id", 0)
    if uid == sister_id and uid != OWNER_ID:
        sender_name = update.effective_user.first_name
        caption = update.message.caption or ""
        await ctx.bot.send_message(
            chat_id=OWNER_ID,
            text=f"📸 *Фото от сестры ({sender_name}):*\n{caption}",
            parse_mode="Markdown"
        )
        await ctx.bot.forward_message(
            chat_id=OWNER_ID,
            from_chat_id=update.effective_chat.id,
            message_id=update.message.message_id
        )
        await update.message.reply_text("✅ Отправила! Спасибо 🙏")
        buttons = [
            [InlineKeyboardButton(f"✅ Это {c['name']}", callback_data=f"sister_{k}_done")]
            for k, c in cfg["counters"].items() if not c["done"]
        ]
        if buttons:
            await ctx.bot.send_message(
                chat_id=OWNER_ID,
                text="Отметь какие показания получил:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )

# ─────────────────────────────────────────────
#  Сообщения сестре — команды
# ─────────────────────────────────────────────
async def cmd_love(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return ConversationHandler.END
    love = cfg.get("love", {})
    if love.get("enabled"):
        day_num = days_since_start()
        start = datetime.fromisoformat(love["start_date"]).strftime("%d.%m.%Y")
        await update.message.reply_text(
            f"💛 *Ежедневные сообщения сестре включены*\n\n"
            f"├ Отсчёт с: {start}\n"
            f"├ Сегодня: день *{day_num}*\n"
            f"└ Время отправки: {love.get('send_time')}\n\n"
            f"Что хочешь изменить?\n"
            f"├ /love\\_date — изменить дату отсчёта\n"
            f"├ /love\\_test — тест прямо сейчас\n"
            f"└ /love\\_off — выключить\n\n"
            f"Или введи новое время (`ЧЧ:ММ`) чтобы изменить расписание:",
            parse_mode="Markdown"
        )
        return WAITING_LOVE_TIME
    else:
        await update.message.reply_text(
            "💛 *Настройка ежедневных сообщений сестре*\n\n"
            "Введи дату отсчёта в формате `ДД.ММ.ГГГГ`\n"
            "Например: `01.09.2023`\n\n"
            "_(С этой даты будет считаться день — «сегодня 368-й день»)_",
            parse_mode="Markdown"
        )
        return WAITING_LOVE_DATE

async def cmd_love_date(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Изменить дату отсчёта в любой момент."""
    if update.effective_user.id != OWNER_ID:
        return ConversationHandler.END
    love = cfg.get("love", {})
    current = ""
    if love.get("start_date"):
        d = datetime.fromisoformat(love["start_date"]).strftime("%d.%m.%Y")
        current = f"Текущая дата: *{d}*\n\n"
    await update.message.reply_text(
        f"📅 *Изменить дату отсчёта*\n\n"
        f"{current}"
        f"Введи новую дату в формате `ДД.ММ.ГГГГ`:",
        parse_mode="Markdown"
    )
    return WAITING_LOVE_DATE

async def love_get_date(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        d = datetime.strptime(text, "%d.%m.%Y").date()
        assert d <= date.today()
    except (ValueError, AssertionError):
        await update.message.reply_text(
            "❌ Неверный формат или дата в будущем.\nВведи: `ДД.ММ.ГГГГ`",
            parse_mode="Markdown"
        )
        return WAITING_LOVE_DATE

    days = (date.today() - d).days + 1
    ctx.user_data["love_start_date"] = d.isoformat()

    # Если уже настроено — просто обновляем дату, не спрашиваем время
    if cfg["love"].get("enabled") and cfg["love"].get("send_time"):
        cfg["love"]["start_date"] = d.isoformat()
        save_config(cfg)
        await update.message.reply_text(
            f"✅ Дата обновлена: *{d.strftime('%d.%m.%Y')}*\n"
            f"Сегодня — день *{days}* 🎉",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    await update.message.reply_text(
        f"✅ Дата: *{d.strftime('%d.%m.%Y')}* — сегодня день *{days}*!\n\n"
        f"Теперь введи время отправки в формате `ЧЧ:ММ`\nНапример: `09:00`",
        parse_mode="Markdown"
    )
    return WAITING_LOVE_TIME

async def love_get_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        h, m = map(int, text.split(":"))
        assert 0 <= h <= 23 and 0 <= m <= 59
        time_str = f"{h:02d}:{m:02d}"
    except (ValueError, AssertionError):
        await update.message.reply_text("❌ Формат: `ЧЧ:ММ`, например `09:00`", parse_mode="Markdown")
        return WAITING_LOVE_TIME

    # Если уже включено — только обновляем время
    if cfg["love"].get("enabled") and not ctx.user_data.get("love_start_date"):
        cfg["love"]["send_time"] = time_str
        save_config(cfg)
        rebuild_schedule(ctx.application)
        await update.message.reply_text(f"✅ Время обновлено: *{time_str}*", parse_mode="Markdown")
        return ConversationHandler.END

    start_date = ctx.user_data.get("love_start_date")
    if not start_date:
        await update.message.reply_text("❌ Ошибка. Начни заново: /love")
        return ConversationHandler.END

    cfg["love"]["enabled"] = True
    cfg["love"]["start_date"] = start_date
    cfg["love"]["send_time"] = time_str
    cfg["love"]["msg_index"] = 0
    save_config(cfg)
    rebuild_schedule(ctx.application)

    days = (date.today() - date.fromisoformat(start_date)).days + 1
    await update.message.reply_text(
        f"✅ *Включено!*\n\n"
        f"├ Начало: {datetime.fromisoformat(start_date).strftime('%d.%m.%Y')}\n"
        f"├ Сейчас: день *{days}*\n"
        f"└ Каждый день в *{time_str}* — новое сообщение 💛\n\n"
        f"/love\\_test — отправить тест прямо сейчас",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cmd_love_off(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    cfg["love"]["enabled"] = False
    save_config(cfg)
    rebuild_schedule(ctx.application)
    await update.message.reply_text("❌ Ежедневные сообщения выключены.")

async def cmd_love_test(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    
    day_num = days_since_start() or 1
    text = await generate_love_message(day_num, ctx.bot)
    
    # Очищаем от спецсимволов HTML и звездочек Markdown
    clean_text = re.sub(r"[<>&*]", "", text)
    
    cfg["love"]["last_text"] = text
    save_config(cfg)
    
    await update.message.reply_text(
        f"<code>{clean_text}</code>", 
        parse_mode="HTML"
    )

# ─────────────────────────────────────────────
#  Callback handler
# ─────────────────────────────────────────────
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = update.effective_user.id

    if data.startswith("done_") and uid == OWNER_ID:
        key = data[5:]
        if key in cfg["counters"]:
            mark_done(key)
            name = cfg["counters"][key]["name"]
            await query.edit_message_text(
                f"✅ *{name}* — отмечен!\n\n" + status_text(),
                parse_mode="Markdown", reply_markup=main_keyboard()
            )

    elif data == "status" and uid == OWNER_ID:
        await query.edit_message_text(status_text(), parse_mode="Markdown", reply_markup=main_keyboard())

    elif data.startswith("sister_") and data.endswith("_done") and uid == OWNER_ID:
        parts = data.split("_")
        key = parts[1]
        if key in cfg["counters"]:
            mark_done(key)
            name = cfg["counters"][key]["name"]
            await query.edit_message_text(f"✅ *{name}* — получен!", parse_mode="Markdown")

    elif data.startswith("del_") and uid == OWNER_ID:
        key = data[4:]
        if key in cfg["counters"]:
            name = cfg["counters"][key]["name"]
            del cfg["counters"][key]
            save_config(cfg)
            rebuild_schedule(ctx.application)
            await query.edit_message_text(f"🗑 *{name}* удалён.", parse_mode="Markdown")

    elif data.startswith("setd_") and uid == OWNER_ID:
        key = data[5:]
        if key in cfg["counters"]:
            ctx.user_data["deadline_key"] = key
            name = cfg["counters"][key]["name"]
            await query.edit_message_text(
                f"📅 *{name}*\n\nВведи новый дедлайн (1–28):", parse_mode="Markdown"
            )

    elif data.startswith("ping_sister_") and uid == OWNER_ID:
        key = data[len("ping_sister_"):]
        if key in cfg["counters"]:
            await notify_sister(ctx.bot, [key])
            name = cfg["counters"][key]["name"]
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(f"✅ {name} — отправил", callback_data=f"done_{key}"),
            ]]))

    elif data == "sister_force_all" and uid == OWNER_ID:
        all_pending = [k for k, c in cfg["counters"].items() if not c["done"]]
        if all_pending:
            await notify_sister(ctx.bot, all_pending)
            names = ", ".join(cfg["counters"][k]["name"] for k in all_pending)
            await query.edit_message_text(f"✅ Написал сестре насчёт: *{names}*", parse_mode="Markdown")
        else:
            await query.edit_message_text("✅ Все показания уже отправлены!")

    elif data == "cancel":
        await query.edit_message_text("❌ Отменено.")

# ─────────────────────────────────────────────
#  Post init & Main
# ─────────────────────────────────────────────
async def post_init(app: Application):
    rebuild_schedule(app)
    scheduler.start()
    logger.info("Bot started.")

def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", cmd_add)],
        states={
            WAITING_COUNTER_NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, add_get_name)],
            WAITING_COUNTER_DEADLINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_get_deadline)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
    )
    deadline_conv = ConversationHandler(
        entry_points=[CommandHandler("deadline", cmd_deadline)],
        states={
            WAITING_NEW_DEADLINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, deadline_get_day)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
    )
    love_conv = ConversationHandler(
        entry_points=[
            CommandHandler("love", cmd_love),
            CommandHandler("love_date", cmd_love_date),
        ],
        states={
            WAITING_LOVE_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, love_get_date)],
            WAITING_LOVE_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, love_get_time)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
    )

    app.add_handler(add_conv)
    app.add_handler(deadline_conv)
    app.add_handler(love_conv)
    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("status",     cmd_status))
    app.add_handler(CommandHandler("remind",     cmd_remind))
    app.add_handler(CommandHandler("delete",     cmd_delete))
    app.add_handler(CommandHandler("settings",   cmd_settings))
    app.add_handler(CommandHandler("set_times",  cmd_set_times))
    app.add_handler(CommandHandler("sister",     cmd_sister))
    app.add_handler(CommandHandler("love_off",   cmd_love_off))
    app.add_handler(CommandHandler("love_test",  cmd_love_test))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
