# telegram_prayer_topic_closer.py
# Requires: python-telegram-bot==22.3 requests tzdata Flask

import asyncio
import json
import os
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
from threading import Thread

import requests
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --------------------- CONFIG ---------------------
BOT_TOKEN = os.getenv("TOKEN")   # <-- set TOKEN in Render
if not BOT_TOKEN:
    print("⚠️ BOT_TOKEN not set in env vars; set TOKEN or the program will exit on start.")

LAT = 36.7538
LON = 3.0588
METHOD = 3
TIMEZONE = "Africa/Algiers"

DURATIONS = {
    "Fajr": 15,
    "Dhuhr": 25,
    "Asr": 25,
    "Maghrib": 20,
    "Isha": 25,
}

CONFIG_FILE = "topic_config.json"
PRAYERS = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]
# --------------------------------------------------

app = Flask(__name__)

@app.route("/")
def index():
    return "OK", 200

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

# ------------------- COMMANDS -------------------

async def bind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_message is None:
        return
    chat_id = update.effective_chat.id
    thread_id = update.effective_message.message_thread_id
    if thread_id is None:
        await update.effective_message.reply_text("⚠️ قم بتفعيل المواضيع ثم نفذ /bind داخل الموضوع المطلوب.")
        return

    cfg = load_config()
    # overwrite previous binding for this chat
    cfg["bindings"] = [{"chat_id": chat_id, "thread_id": thread_id}]
    save_config(cfg)

    await update.effective_message.reply_text("✅ تم حفظ الربط مع هذا الموضوع.")

async def testclose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg = load_config()
    if not cfg.get("bindings"):
        await update.effective_message.reply_text("⚠️ لا يوجد ربط. استعمل /bind داخل الموضوع أولاً.")
        return
    b = cfg["bindings"][-1]

    await context.bot.send_message(chat_id=b["chat_id"], message_thread_id=b["thread_id"], text="⏳ سيتم غلق الموضوع (تجربة)...")
    await context.bot.closeForumTopic(chat_id=b["chat_id"], message_thread_id=b["thread_id"])

async def testopen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg = load_config()
    if not cfg.get("bindings"):
        await update.effective_message.reply_text("⚠️ لا يوجد ربط. استعمل /bind داخل الموضوع أولاً.")
        return
    b = cfg["bindings"][-1]

    await context.bot.reopenForumTopic(chat_id=b["chat_id"], message_thread_id=b["thread_id"])
    await context.bot.send_message(chat_id=b["chat_id"], message_thread_id=b["thread_id"], text="✅ تم إعادة فتح الموضوع (تجربة)")

# ------------------- PRAYER TIMES -------------------

def fetch_prayer_times(d: date):
    tz = ZoneInfo(TIMEZONE)
    url = (
        f"https://api.aladhan.com/v1/timings/{d.isoformat()}?"
        f"latitude={LAT}&longitude={LON}&method={METHOD}&timezonestring={TIMEZONE}"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    data = r.json()["data"]["timings"]
    out = {}
    for name in PRAYERS:
        hh, mm = data[name].split(":")[:2]
        dt = datetime.combine(d, time(int(hh), int(mm)), tzinfo=tz)
        out[name] = dt
    return out

async def close_then_open(context: ContextTypes.DEFAULT_TYPE, prayer_name: str):
    cfg = load_config()
    if not cfg.get("bindings"):
        return
    b = cfg["bindings"][-1]
    chat_id = b["chat_id"]
    thread_id = b["thread_id"]

    messages = {
        "Fajr": "🕌 صلاة الفجر يرحمكم الله",
        "Dhuhr": "🕌 صلاة الظهر يرحمكم الله",
        "Asr": "🕌 صلاة العصر يرحمكم الله",
        "Maghrib": "🕌 صلاة المغرب يرحمكم الله",
        "Isha": "🕌 صلاة العشاء يرحمكم الله",
    }

    msg = messages.get(prayer_name, f"⏳ وقت الصلاة: {prayer_name}")
    await context.bot.send_message(chat_id=chat_id, message_thread_id=thread_id, text=msg)

    # close after sending
    await context.bot.closeForumTopic(chat_id=chat_id, message_thread_id=thread_id)

    # wait prayer duration
    minutes = DURATIONS.get(prayer_name, 20)
    await asyncio.sleep(minutes * 60)

    # reopen
    await context.bot.reopenForumTopic(chat_id=chat_id, message_thread_id=thread_id)
    await context.bot.send_message(chat_id=chat_id, message_thread_id=thread_id, text=f"✅ تم إعادة فتح الموضوع بعد صلاة {prayer_name}.")

# ------------------- DAILY TIMES POST -------------------

async def post_daily_times(context: ContextTypes.DEFAULT_TYPE):
    cfg = load_config()
    if not cfg.get("bindings"):
        return
    b = cfg["bindings"][-1]
    chat_id = b["chat_id"]
    thread_id = b["thread_id"]

    tz = ZoneInfo(TIMEZONE)
    today = datetime.now(tz).date()
    times = fetch_prayer_times(today)
    date_str = today.strftime("%d-%m-%Y")

    msg = f"🕌 أوقات الصلاة ليوم {date_str} (الجزائر العاصمة):\n\n"
    arabic_names = {
        "Fajr": "الفجر",
        "Dhuhr": "الظهر",
        "Asr": "العصر",
        "Maghrib": "المغرب",
        "Isha": "العشاء",
    }
    for name, dt in times.items():
        msg += f"{arabic_names.get(name, name)}: {dt.strftime('%H:%M')}\n"

    await context.bot.send_message(chat_id=chat_id, message_thread_id=thread_id, text=msg)

def schedule_today(application: Application):
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    times = fetch_prayer_times(now.date())

    # Schedule closures
    for name, when_dt in times.items():
        if when_dt > now + timedelta(seconds=5):
            async def job(ctx: ContextTypes.DEFAULT_TYPE, prayer=name):
                await close_then_open(ctx, prayer)
            application.job_queue.run_once(job, when=when_dt)

    # Schedule tomorrow’s daily post & re-schedule tasks
    midnight_tomorrow = datetime.combine(now.date() + timedelta(days=1), time(0, 5), tzinfo=tz)

    async def tomorrow_job(ctx: ContextTypes.DEFAULT_TYPE):
        await post_daily_times(ctx)
        schedule_today(application)

    application.job_queue.run_once(tomorrow_job, when=midnight_tomorrow)

# ------------------- EXTRA COMMANDS -------------------

async def times_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tz = ZoneInfo(TIMEZONE)
    today = datetime.now(tz).date()
    times = fetch_prayer_times(today)
    date_str = today.strftime("%d-%m-%Y")

    msg = f"🕌 أوقات الصلاة ليوم {date_str} (الجزائر العاصمة):\n\n"
    arabic_names = {
        "Fajr": "الفجر",
        "Dhuhr": "الظهر",
        "Asr": "العصر",
        "Maghrib": "المغرب",
        "Isha": "العشاء",
    }
    for name, dt in times.items():
        msg += f"{arabic_names.get(name, name)}: {dt.strftime('%H:%M')}\n"

    await update.message.reply_text(msg)

# ------------------- BOT SETUP -------------------

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "السلام عليكم 👋\n\n"
        "استعمل /bind داخل موضوع للتحكم فيه.\n\n"
        "الأوامر المتوفرة:\n"
        "/testclose\n/testopen\n/times"
    )

async def on_ready(app: Application):
    # Post today's times immediately once bot starts
    dummy_ctx = type("Dummy", (), {"bot": app.bot})
    try:
        await post_daily_times(dummy_ctx)
    except Exception as e:
        print("Could not post daily times:", e)

    # Schedule future
    schedule_today(app)

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN not set. Exiting.")
        return

    application = Application.builder().token(BOT_TOKEN).build()

# Ensure JobQueue exists
if application.job_queue is None:
    application.job_queue = application.job_queue_class(application)

    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("bind", bind))
    application.add_handler(CommandHandler("testclose", testclose))
    application.add_handler(CommandHandler("testopen", testopen))
    application.add_handler(CommandHandler("times", times_cmd))
    application.post_init = on_ready

    # start keep-alive web server in a thread
    t = Thread(target=run_flask, daemon=True)
    t.start()

    # run the bot (blocks)
    application.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
