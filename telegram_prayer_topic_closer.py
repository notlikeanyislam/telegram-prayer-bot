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
BOT_TOKEN = os.getenv("BOT_TOKEN")   # <-- set BOT_TOKEN in Render
if not TOKEN:
    print("⚠️ BOT_TOKEN not set in env vars; set BOT_TOKEN or the program will exit on start.")

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

async def bind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_message is None:
        return
    chat_id = update.effective_chat.id
    thread_id = update.effective_message.message_thread_id
    if thread_id is None:
        await update.effective_message.reply_text("Enable Topics and run /bind inside the target topic.")
        return
    cfg = load_config()
    cfg.setdefault("bindings", [])
    # store per-chat bindings (simple append)
    cfg["bindings"].append({"chat_id": chat_id, "thread_id": thread_id})
    save_config(cfg)
    await update.effective_message.reply_text(f"Saved!\nchat_id={chat_id}\nthread_id={thread_id}")

async def testclose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg = load_config()
    # use latest binding
    if not cfg.get("bindings"):
        await update.effective_message.reply_text("No binding found. Run /bind inside the topic.")
        return
    b = cfg["bindings"][-1]
    await context.bot.closeForumTopic(chat_id=b["chat_id"], message_thread_id=b["thread_id"])
    await context.bot.send_message(chat_id=b["chat_id"], message_thread_id=b["thread_id"], text="⏳ Topic closed (test)")

async def testopen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg = load_config()
    if not cfg.get("bindings"):
        await update.effective_message.reply_text("No binding found. Run /bind inside the topic.")
        return
    b = cfg["bindings"][-1]
    await context.bot.reopenForumTopic(chat_id=b["chat_id"], message_thread_id=b["thread_id"])
    await context.bot.send_message(chat_id=b["chat_id"], message_thread_id=b["thread_id"], text="✅ Topic reopened (test)")

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

    await context.bot.closeForumTopic(chat_id=chat_id, message_thread_id=thread_id)
    messages = {
        "Fajr": "صلاة الفجر يرحمكم الله",
        "Dhuhr": "صلاة الظهر يرحمكم الله",
        "Asr": "صلاة العصر يرحمكم الله",
        "Maghrib": "صلاة المغرب يرحمكم الله",
        "Isha": "صلاة العشاء يرحمكم الله",
    }
    # send closing message
    msg = messages.get(prayer_name, f"⏳ وقت الصلاة: {prayer_name}")
    await context.bot.send_message(chat_id=chat_id, message_thread_id=thread_id, text=msg)

    minutes = DURATIONS.get(prayer_name, 20)
    await asyncio.sleep(minutes * 60)

    await context.bot.reopenForumTopic(chat_id=chat_id, message_thread_id=thread_id)
    await context.bot.send_message(chat_id=chat_id, message_thread_id=thread_id, text=f"✅ Topic reopened after {prayer_name}.")

def schedule_today(application: Application):
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    t = fetch_prayer_times(now.date())
    for name, when_dt in t.items():
        if when_dt > now + timedelta(seconds=5):
            # capture name in default arg
            application.job_queue.run_once(lambda ctx, n=name: asyncio.create_task(close_then_open(ctx, n)), when=when_dt)
    midnight_tomorrow = datetime.combine(now.date() + timedelta(days=1), time(0,5), tzinfo=tz)
    application.job_queue.run_once(lambda ctx: schedule_today(application), when=midnight_tomorrow)

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Salaam! Use /bind in a topic to control it. Commands: /testclose /testopen")

async def on_ready(app: Application):
    schedule_today(app)

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def main():
    if not TOKEN:
        print("ERROR: BOT_TOKEN not set. Exiting.")
        return

    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("bind", bind))
    application.add_handler(CommandHandler("testclose", testclose))
    application.add_handler(CommandHandler("testopen", testopen))
    application.post_init = on_ready

    # start keep-alive web server in a thread
    t = Thread(target=run_flask, daemon=True)
    t.start()

    # run the bot (blocks)
    application.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
