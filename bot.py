import json
import logging
import os
from datetime import datetime
from pathlib import Path

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
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
OWNER_ID  = int(os.getenv("OWNER_ID", "0"))
SISTER_ID = int(os.getenv("SISTER_ID", "0"))
CONFIG_FILE = Path("config.json")

# ─────────────────────────────────────────────
#  Default config
# ─────────────────────────────────────────────
DEFAULT_CONFIG = {
    "counters": {
        "light": {
            "name": "Свет 💡",
            "deadline_day": 30,
            "done": False,
            "last_month": None,
        },
        "water": {
            "name": "Вода 💧",
            "deadline_day": 20,
            "done": False,
            "last_month": None,
        },
    },
    # За сколько дней → в какие часы напоминать (для каждого счётчика своё)
    # Общее расписание — применяется если у счётчика нет своего
    "default_schedule": {
        "5": ["09:00"],
        "2": ["09:00", "20:00"],
        "0": ["09:00", "13:00", "17:00", "20:00"],
    },
    "sister": {
        "chat_id": SISTER_ID,
    },
}

# ConversationHandler states
WAITING_COUNTER_NAME, WAITING_COUNTER_DEADLINE = range(2)
WAITING_DELETE_CONFIRM = 2
WAITING_NEW_DEADLINE = 3

# ─────────────────────────────────────────────
#  Config helpers
# ─────────────────────────────────────────────
def load_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    return json.loads(json.dumps(DEFAULT_CONFIG))

def save_config(cfg: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

cfg = load_config()

# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────
def current_month() -> str:
    return datetime.now().strftime("%Y-%m")

def reset_if_new_month():
    month = current_month()
    changed = False
    for c in cfg["counters"].values():
        if c.get("last_month") != month:
            c["done"] = False
            changed = True
    if changed:
        save_config(cfg)

def mark_done(key: str):
    cfg["counters"][key]["done"] = True
    cfg["counters"][key]["last_month"] = current_month()
    save_config(cfg)

def status_text() -> str:
    reset_if_new_month()
    month = datetime.now().strftime("%m.%Y")
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
                f"✅ {c['name']} — отправил",
                callback_data=f"done_{key}"
            )])
    buttons.append([InlineKeyboardButton("📋 Обновить статус", callback_data="status")])
    return InlineKeyboardMarkup(buttons)

def counters_list_keyboard(action: str) -> InlineKeyboardMarkup:
    """Список счётчиков для выбора действия (удалить / изменить дедлайн)."""
    buttons = []
    for key, c in cfg["counters"].items():
        buttons.append([InlineKeyboardButton(
            f"{c['name']} (дедлайн {c['deadline_day']}-е)",
            callback_data=f"{action}_{key}"
        )])
    buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(buttons)

# ─────────────────────────────────────────────
#  Scheduler
# ─────────────────────────────────────────────
scheduler = AsyncIOScheduler(timezone="Europe/Kiev")

async def send_reminder(app: Application, counter_key: str):
    reset_if_new_month()
    c = cfg["counters"].get(counter_key)
    if not c or c["done"]:
        return

    today = datetime.now().day
    deadline = c["deadline_day"]
    days_left = deadline - today

    if days_left > 0:
        urgency = f"⏰ До дедлайна *{days_left} дн.*"
    elif days_left == 0:
        urgency = "🚨 *Сегодня последний день!*"
    else:
        urgency = f"🔴 *Просрочено на {abs(days_left)} дн.!*"

    text = (
        f"📟 Напоминание: *{c['name']}*\n\n"
        f"{urgency}\n\n"
        f"Нажми когда отправишь 👇"
    )
    buttons = [[InlineKeyboardButton(f"✅ {c['name']} — отправил", callback_data=f"done_{counter_key}")]]
    await app.bot.send_message(
        chat_id=OWNER_ID,
        text=text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

def rebuild_schedule(app: Application):
    for job in scheduler.get_jobs():
        if job.id.startswith("rem_"):
            job.remove()

    sched = cfg.get("default_schedule", DEFAULT_CONFIG["default_schedule"])

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
        # Незнакомый пользователь — показываем chat_id (для сестры и т.д.)
        await update.message.reply_text(
            f"Привет, {name}! 👋\n\n"
            f"Твой chat\\_id: `{uid}`\n\n"
            f"Передай его хозяину бота.",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        "👋 *Бот напоминаний*\n\n"
        "├ /status — статус счётчиков\n"
        "├ /add — добавить счётчик\n"
        "├ /delete — удалить счётчик\n"
        "├ /deadline — изменить дедлайн\n"
        "├ /remind — напомнить прямо сейчас\n"
        "├ /sister — написать сестре\n"
        "└ /settings — расписание напоминаний",
        parse_mode="Markdown"
    )

# ─────────────────────────────────────────────
#  /status
# ─────────────────────────────────────────────
async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    await update.message.reply_text(
        status_text(), parse_mode="Markdown", reply_markup=main_keyboard()
    )

# ─────────────────────────────────────────────
#  /remind
# ─────────────────────────────────────────────
async def cmd_remind(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    for key in cfg["counters"]:
        await send_reminder(ctx.application, key)

# ─────────────────────────────────────────────
#  /add — ConversationHandler
# ─────────────────────────────────────────────
async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return ConversationHandler.END
    await update.message.reply_text(
        "➕ *Новый счётчик*\n\nВведи название (например: `Газ 🔥` или `Вода 💧`):",
        parse_mode="Markdown"
    )
    return WAITING_COUNTER_NAME

async def add_get_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_counter_name"] = update.message.text.strip()
    await update.message.reply_text(
        f"📅 Название: *{ctx.user_data['new_counter_name']}*\n\n"
        f"Введи дедлайн — число месяца (1–28):",
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
    # Генерируем ключ из имени
    key = name.lower().replace(" ", "_")
    key = "".join(c for c in key if c.isalnum() or c == "_")[:20]
    if not key:
        key = f"counter_{len(cfg['counters'])+1}"

    cfg["counters"][key] = {
        "name": name,
        "deadline_day": day,
        "done": False,
        "last_month": None,
    }
    save_config(cfg)
    rebuild_schedule(ctx.application)

    await update.message.reply_text(
        f"✅ Добавлен: *{name}* — дедлайн *{day}-е* число.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def add_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Отменено.")
    return ConversationHandler.END

# ─────────────────────────────────────────────
#  /delete
# ─────────────────────────────────────────────
async def cmd_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not cfg["counters"]:
        await update.message.reply_text("Нет счётчиков для удаления.")
        return
    await update.message.reply_text(
        "🗑 *Какой счётчик удалить?*",
        parse_mode="Markdown",
        reply_markup=counters_list_keyboard("del")
    )

# ─────────────────────────────────────────────
#  /deadline
# ─────────────────────────────────────────────
async def cmd_deadline(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return ConversationHandler.END
    if not cfg["counters"]:
        await update.message.reply_text("Нет счётчиков.")
        return ConversationHandler.END
    await update.message.reply_text(
        "📅 *Для какого счётчика изменить дедлайн?*",
        parse_mode="Markdown",
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
        name = cfg["counters"][key]["name"]
        await update.message.reply_text(
            f"✅ *{name}* — дедлайн изменён на *{day}-е* число.",
            parse_mode="Markdown"
        )
    return ConversationHandler.END

# ─────────────────────────────────────────────
#  /settings
# ─────────────────────────────────────────────
async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    sched = cfg.get("default_schedule", DEFAULT_CONFIG["default_schedule"])
    lines = []
    for days, times in sorted(sched.items(), key=lambda x: -int(x[0])):
        d = int(days)
        label = f"За {d} дн." if d > 0 else "В день дедлайна"
        lines.append(f"• {label}: {', '.join(times)}")

    counters_info = []
    for c in cfg["counters"].values():
        counters_info.append(f"• {c['name']} — дедлайн {c['deadline_day']}-е")

    text = (
        "⚙️ *Настройки*\n\n"
        "*Счётчики:*\n" + "\n".join(counters_info) + "\n\n"
        "*Расписание напоминаний:*\n" + "\n".join(lines) + "\n\n"
        "*Изменить расписание:*\n"
        "`/set_times 2 09:00 20:00`\n"
        "`/set_times 0 09:00 13:00 17:00 20:00`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

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
        await update.message.reply_text(
            "❌ Использование: `/set_times 2 09:00 20:00`", parse_mode="Markdown"
        )
        return
    cfg.setdefault("default_schedule", {})[str(days_before)] = times
    save_config(cfg)
    rebuild_schedule(ctx.application)
    await update.message.reply_text(
        f"✅ За *{days_before}* дн.: {', '.join(times)}", parse_mode="Markdown"
    )

# ─────────────────────────────────────────────
#  /sister
# ─────────────────────────────────────────────
async def cmd_sister(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return

    sister_id = cfg["sister"].get("chat_id", 0)
    if not sister_id:
        await update.message.reply_text(
            "❌ chat\\_id сестры не задан.\n\n"
            "Попроси её написать `/start` боту — он покажет её id.\n"
            "Добавь `SISTER_ID=<id>` в переменные Railway.",
            parse_mode="Markdown"
        )
        return

    pending = {k: c for k, c in cfg["counters"].items() if not c["done"]}
    if not pending:
        await update.message.reply_text("✅ Все показания уже отправлены!")
        return

    names = ", ".join(c["name"] for c in pending.values())
    try:
        await ctx.bot.send_message(
            chat_id=sister_id,
            text=(
                f"Привет! 👋\n\n"
                f"Пришли, пожалуйста, *фото показаний*:\n"
                f"*{names}*\n\n"
                f"Просто отправь фотографии сюда — они придут мне автоматически 📸"
            ),
            parse_mode="Markdown"
        )
        await update.message.reply_text(
            f"✅ Написал сестре насчёт: {names}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

# ─────────────────────────────────────────────
#  Фото от сестры → пересылка владельцу
# ─────────────────────────────────────────────
async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    sister_id = cfg["sister"].get("chat_id", 0)

    # Фото от сестры
    if uid == sister_id and uid != OWNER_ID:
        caption = update.message.caption or ""
        sender_name = update.effective_user.first_name

        # Пересылаем все фото владельцу
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

        # Показываем кнопки — что это были за показания
        if cfg["counters"]:
            buttons = []
            for key, c in cfg["counters"].items():
                if not c["done"]:
                    buttons.append([InlineKeyboardButton(
                        f"✅ Это {c['name']}",
                        callback_data=f"sister_{key}_done"
                    )])
            if buttons:
                await ctx.bot.send_message(
                    chat_id=OWNER_ID,
                    text="Отметь какие показания получил:",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )

    elif uid == OWNER_ID:
        # Фото от владельца — просто игнорируем или можно добавить обработку
        pass

# ─────────────────────────────────────────────
#  Callback handler
# ─────────────────────────────────────────────
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = update.effective_user.id

    # ── Отметить выполненным (владелец) ──
    if data.startswith("done_") and uid == OWNER_ID:
        key = data[5:]
        if key in cfg["counters"]:
            mark_done(key)
            name = cfg["counters"][key]["name"]
            await query.edit_message_text(
                f"✅ *{name}* — отмечен!\n\n" + status_text(),
                parse_mode="Markdown",
                reply_markup=main_keyboard()
            )

    # ── Статус ──
    elif data == "status" and uid == OWNER_ID:
        await query.edit_message_text(
            status_text(), parse_mode="Markdown", reply_markup=main_keyboard()
        )

    # ── Сестра отметила что прислала (кнопка у владельца) ──
    elif data.startswith("sister_") and data.endswith("_done") and uid == OWNER_ID:
        parts = data.split("_")
        key = parts[1]
        if key in cfg["counters"]:
            mark_done(key)
            name = cfg["counters"][key]["name"]
            await query.edit_message_text(f"✅ *{name}* — отмечен как получен!", parse_mode="Markdown")

    # ── Удалить счётчик ──
    elif data.startswith("del_") and uid == OWNER_ID:
        key = data[4:]
        if key in cfg["counters"]:
            name = cfg["counters"][key]["name"]
            del cfg["counters"][key]
            save_config(cfg)
            rebuild_schedule(ctx.application)
            await query.edit_message_text(f"🗑 *{name}* удалён.", parse_mode="Markdown")

    # ── Выбор счётчика для изменения дедлайна ──
    elif data.startswith("setd_") and uid == OWNER_ID:
        key = data[5:]
        if key in cfg["counters"]:
            ctx.user_data["deadline_key"] = key
            name = cfg["counters"][key]["name"]
            await query.edit_message_text(
                f"📅 *{name}*\n\nВведи новый дедлайн (число месяца, 1–28):",
                parse_mode="Markdown"
            )

    # ── Отмена ──
    elif data == "cancel":
        await query.edit_message_text("❌ Отменено.")

# ─────────────────────────────────────────────
#  Post init
# ─────────────────────────────────────────────
async def post_init(app: Application):
    rebuild_schedule(app)
    scheduler.start()
    logger.info("Bot started.")

# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────
def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # ConversationHandler для /add
    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", cmd_add)],
        states={
            WAITING_COUNTER_NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, add_get_name)],
            WAITING_COUNTER_DEADLINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_get_deadline)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
    )

    # ConversationHandler для /deadline (ввод нового числа)
    deadline_conv = ConversationHandler(
        entry_points=[CommandHandler("deadline", cmd_deadline)],
        states={
            WAITING_NEW_DEADLINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, deadline_get_day)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
    )

    app.add_handler(add_conv)
    app.add_handler(deadline_conv)
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("remind",    cmd_remind))
    app.add_handler(CommandHandler("delete",    cmd_delete))
    app.add_handler(CommandHandler("settings",  cmd_settings))
    app.add_handler(CommandHandler("set_times", cmd_set_times))
    app.add_handler(CommandHandler("sister",    cmd_sister))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
