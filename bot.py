import asyncio
import json
import logging
import os
from datetime import datetime, time
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

# ──────────────────────────────────────────────
#  Logging
# ──────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s │ %(levelname)s │ %(name)s │ %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  Config
# ──────────────────────────────────────────────
BOT_TOKEN   = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
OWNER_ID    = int(os.getenv("OWNER_ID", "0"))       # твой Telegram user_id
SISTER_ID   = int(os.getenv("SISTER_ID", "0"))      # chat_id сестры (0 = не задан)
CONFIG_FILE = Path("config.json")

DEFAULT_CONFIG = {
    "deadline_day": 20,          # день месяца — дедлайн
    "counters": {
        "gas":   {"name": "Газ",   "done": False, "last_month": None},
        "light": {"name": "Свет",  "done": False, "last_month": None},
    },
    "schedule": {
        # За сколько дней до дедлайна начинать и сколько раз в день
        # ключ — "days_before", значение — список часов (24h)
        "5": ["09:00"],
        "2": ["09:00", "20:00"],
        "0": ["09:00", "13:00", "17:00", "20:00"],   # день дедлайна
    },
    "sister": {
        "chat_id": SISTER_ID,
        "ask_gas":   True,
        "ask_light": True,
    }
}

# ──────────────────────────────────────────────
#  Config helpers
# ──────────────────────────────────────────────
def load_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        # merge missing keys
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    return DEFAULT_CONFIG.copy()

def save_config(cfg: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

cfg = load_config()

# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────
def current_month_key() -> str:
    return datetime.now().strftime("%Y-%m")

def mark_done(counter_key: str):
    cfg["counters"][counter_key]["done"] = True
    cfg["counters"][counter_key]["last_month"] = current_month_key()
    save_config(cfg)

def reset_month_if_needed():
    """Сбрасывает done в начале нового месяца."""
    month = current_month_key()
    for key, c in cfg["counters"].items():
        if c.get("last_month") != month:
            c["done"] = False
    save_config(cfg)

def counters_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for key, c in cfg["counters"].items():
        status = "✅" if c["done"] else "⏳"
        buttons.append([InlineKeyboardButton(
            f"{status} {c['name']} — отправил",
            callback_data=f"done_{key}"
        )])
    buttons.append([InlineKeyboardButton("📋 Статус", callback_data="status")])
    return InlineKeyboardMarkup(buttons)

def status_text() -> str:
    reset_month_if_needed()
    month = datetime.now().strftime("%B %Y")
    lines = [f"📊 *Счётчики — {month}*\n"]
    for key, c in cfg["counters"].items():
        icon = "✅" if c["done"] else "❌"
        lines.append(f"{icon} {c['name']}")
    lines.append(f"\n🗓 Дедлайн: {cfg['deadline_day']}-е число")
    return "\n".join(lines)

# ──────────────────────────────────────────────
#  Scheduler logic
# ──────────────────────────────────────────────
scheduler = AsyncIOScheduler(timezone="Europe/Kiev")

async def send_reminder(app: Application, counter_keys: list[str]):
    reset_month_if_needed()
    pending = [k for k in counter_keys if not cfg["counters"][k]["done"]]
    if not pending:
        return

    names = " и ".join(cfg["counters"][k]["name"] for k in pending)
    today = datetime.now().day
    deadline = cfg["deadline_day"]
    days_left = deadline - today

    if days_left > 0:
        urgency = f"⏰ До дедлайна *{days_left} дн.*"
    elif days_left == 0:
        urgency = "🚨 *Сегодня дедлайн!*"
    else:
        urgency = f"🔴 *Просрочено на {abs(days_left)} дн.!*"

    text = (
        f"📟 *Напоминание о счётчиках*\n\n"
        f"Нужно передать: *{names}*\n"
        f"{urgency}\n\n"
        f"Нажми кнопку когда отправишь 👇"
    )
    await app.bot.send_message(
        chat_id=OWNER_ID,
        text=text,
        parse_mode="Markdown",
        reply_markup=counters_keyboard()
    )

def rebuild_schedule(app: Application):
    """Пересоздаёт все задачи на основе cfg['schedule'] и cfg['deadline_day']."""
    # Удаляем старые задачи напоминаний
    for job in scheduler.get_jobs():
        if job.id.startswith("reminder_"):
            job.remove()

    deadline = cfg["deadline_day"]
    for days_before_str, times_list in cfg["schedule"].items():
        days_before = int(days_before_str)
        send_day = deadline - days_before

        if send_day < 1:
            send_day = 1

        for t in times_list:
            hour, minute = map(int, t.split(":"))
            job_id = f"reminder_{days_before}_{t.replace(':','')}"
            scheduler.add_job(
                send_reminder,
                CronTrigger(day=send_day, hour=hour, minute=minute),
                args=[app, list(cfg["counters"].keys())],
                id=job_id,
                replace_existing=True,
            )
            logger.info(f"Scheduled: day={send_day} {t} (id={job_id})")

    # Задача сброса в начале месяца
    scheduler.add_job(
        lambda: reset_month_if_needed(),
        CronTrigger(day=1, hour=0, minute=1),
        id="monthly_reset",
        replace_existing=True,
    )

# ──────────────────────────────────────────────
#  Command handlers
# ──────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        # Регистрируем chat_id нового пользователя (для сестры)
        uid = update.effective_user.id
        name = update.effective_user.first_name
        await update.message.reply_text(
            f"Привет, {name}! Твой chat_id: `{uid}`\n"
            "Передай его хозяину бота чтобы он мог тебе писать.",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        "👋 *Бот напоминаний запущен!*\n\n"
        "Команды:\n"
        "├ /status — текущий статус\n"
        "├ /settings — настройки\n"
        "├ /remind — напомни прямо сейчас\n"
        "├ /sister — написать сестре\n"
        "└ /help — справка",
        parse_mode="Markdown"
    )

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    await update.message.reply_text(
        status_text(),
        parse_mode="Markdown",
        reply_markup=counters_keyboard()
    )

async def cmd_remind(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    await send_reminder(ctx.application, list(cfg["counters"].keys()))

async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return

    schedule_lines = []
    for days, times in sorted(cfg["schedule"].items(), key=lambda x: -int(x[0])):
        d = int(days)
        if d == 0:
            label = "В день дедлайна"
        else:
            label = f"За {d} дн. до дедлайна"
        schedule_lines.append(f"• {label}: {', '.join(times)}")

    text = (
        f"⚙️ *Настройки*\n\n"
        f"🗓 Дедлайн: *{cfg['deadline_day']}-е* число каждого месяца\n\n"
        f"🔔 Расписание напоминаний:\n" + "\n".join(schedule_lines) + "\n\n"
        f"*Как изменить:*\n"
        f"├ `/set_deadline 25` — поменять дедлайн на 25-е\n"
        f"├ `/set_times 2 09:00 21:00` — за 2 дня напоминать в 9 и 21\n"
        f"└ `/set_times 0 08:00 12:00 18:00 22:00` — в день дедлайна\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_set_deadline(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    try:
        day = int(ctx.args[0])
        assert 1 <= day <= 28
    except (IndexError, ValueError, AssertionError):
        await update.message.reply_text("❌ Использование: `/set_deadline 20` (1–28)", parse_mode="Markdown")
        return

    cfg["deadline_day"] = day
    save_config(cfg)
    rebuild_schedule(ctx.application)
    await update.message.reply_text(f"✅ Дедлайн установлен на *{day}-е* число.", parse_mode="Markdown")

async def cmd_set_times(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    # /set_times <days_before> <time1> [time2] ...
    try:
        days_before = int(ctx.args[0])
        times = ctx.args[1:]
        assert times
        for t in times:
            h, m = map(int, t.split(":"))
            assert 0 <= h <= 23 and 0 <= m <= 59
    except Exception:
        await update.message.reply_text(
            "❌ Использование: `/set_times 2 09:00 20:00`",
            parse_mode="Markdown"
        )
        return

    cfg["schedule"][str(days_before)] = times
    save_config(cfg)
    rebuild_schedule(ctx.application)
    await update.message.reply_text(
        f"✅ За *{days_before}* дн. до дедлайна: {', '.join(times)}",
        parse_mode="Markdown"
    )

async def cmd_sister(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return

    sister_id = cfg["sister"].get("chat_id", 0)
    if not sister_id:
        await update.message.reply_text(
            "❌ chat_id сестры не задан.\n\n"
            "Попроси её написать `/start` боту — он пришлёт её chat_id.\n"
            "Потом задай: `SISTER_ID=<id>` в переменных Railway.",
            parse_mode="Markdown"
        )
        return

    buttons = []
    if cfg["sister"].get("ask_gas"):
        buttons.append([InlineKeyboardButton("✅ Показания газа скинула!", callback_data="sister_gas_done")])
    if cfg["sister"].get("ask_light"):
        buttons.append([InlineKeyboardButton("✅ Показания света скинула!", callback_data="sister_light_done")])

    kb = InlineKeyboardMarkup(buttons) if buttons else None

    pending = [
        cfg["counters"][k]["name"]
        for k in cfg["counters"]
        if not cfg["counters"][k]["done"]
    ]
    if not pending:
        await update.message.reply_text("✅ Все показания уже отмечены как отправленные!")
        return

    names = " и ".join(pending)
    try:
        await ctx.bot.send_message(
            chat_id=sister_id,
            text=(
                f"Привет! 👋\n\n"
                f"Напоминаю — нужно скинуть показания *{names}*.\n"
                f"Дедлайн: *{cfg['deadline_day']}-е* число.\n\n"
                f"Нажми кнопку когда отправишь 👇"
            ),
            parse_mode="Markdown",
            reply_markup=kb
        )
        await update.message.reply_text("✅ Сообщение сестре отправлено!")
    except Exception as e:
        await update.message.reply_text(f"❌ Не удалось отправить: {e}")

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    text = (
        "📖 *Справка*\n\n"
        "*Основные команды:*\n"
        "├ /status — показать статус счётчиков\n"
        "├ /remind — тестовое напоминание прямо сейчас\n"
        "├ /sister — написать сестре\n"
        "├ /settings — текущие настройки\n\n"
        "*Настройка:*\n"
        "├ /set_deadline 20 — дедлайн на 20-е\n"
        "└ /set_times 5 09:00 — за 5 дней напоминать в 9:00\n\n"
        "*Логика эскалации:*\n"
        "Чем ближе дедлайн → тем чаще напоминания.\n"
        "Всё настраивается через /set_times.\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# ──────────────────────────────────────────────
#  Callback handlers
# ──────────────────────────────────────────────
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("done_"):
        key = data.split("_", 1)[1]
        if key in cfg["counters"]:
            mark_done(key)
            name = cfg["counters"][key]["name"]
            await query.edit_message_text(
                f"✅ *{name}* — отмечен как отправлен!\n\n" + status_text(),
                parse_mode="Markdown",
                reply_markup=counters_keyboard()
            )

    elif data == "status":
        await query.edit_message_text(
            status_text(),
            parse_mode="Markdown",
            reply_markup=counters_keyboard()
        )

    elif data.startswith("sister_") and data.endswith("_done"):
        # Сестра нажала кнопку
        parts = data.split("_")
        counter_key = parts[1]  # gas или light
        if counter_key in cfg["counters"]:
            mark_done(counter_key)
            name = cfg["counters"][counter_key]["name"]
            # Уведомляем владельца
            await ctx.bot.send_message(
                chat_id=OWNER_ID,
                text=f"✅ Сестра отправила показания *{name}*!",
                parse_mode="Markdown"
            )
            await query.edit_message_text(f"✅ Спасибо! Показания *{name}* записаны.", parse_mode="Markdown")

# ──────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────
async def post_init(app: Application):
    rebuild_schedule(app)
    scheduler.start()
    logger.info("Bot started. Scheduler running.")

def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start",        cmd_start))
    app.add_handler(CommandHandler("status",       cmd_status))
    app.add_handler(CommandHandler("remind",       cmd_remind))
    app.add_handler(CommandHandler("settings",     cmd_settings))
    app.add_handler(CommandHandler("set_deadline", cmd_set_deadline))
    app.add_handler(CommandHandler("set_times",    cmd_set_times))
    app.add_handler(CommandHandler("sister",       cmd_sister))
    app.add_handler(CommandHandler("help",         cmd_help))
    app.add_handler(CallbackQueryHandler(on_callback))

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
