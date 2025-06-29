import os
import logging
import sqlite3
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    PollAnswerHandler,
    ContextTypes,
)

# --- Configuration ---
BOT_NAME = "AlphaverseArc_bot"
POINTS_PER_POLL = 1
DB_PATH = "bot_data.db"

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Database setup ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_points (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            points INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS poll_answers (
            poll_id TEXT,
            user_id INTEGER,
            UNIQUE(poll_id, user_id)
        )
    """)
    conn.commit()
    conn.close()

def add_point(user_id: int, username: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO user_points(user_id, username, points)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            points = points + ?,
            username = excluded.username
        """,
        (user_id, username, POINTS_PER_POLL, POINTS_PER_POLL),
    )
    conn.commit()
    conn.close()

def has_answered(poll_id: str, user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT 1 FROM poll_answers WHERE poll_id = ? AND user_id = ?",
        (poll_id, user_id),
    )
    result = c.fetchone()
    conn.close()
    return bool(result)

def mark_answered(poll_id: str, user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO poll_answers(poll_id, user_id) VALUES (?, ?)",
        (poll_id, user_id),
    )
    conn.commit()
    conn.close()

# --- Command handlers ---
async def start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"👋 Hello, {update.effective_user.first_name}! Welcome to {BOT_NAME}.\n"
        "Use /createpoll and follow the prompts."
    )

async def createpoll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Expect args: Question? Option1;Option2;...
    text = update.message.text.partition(" ")[2]
    if "?" not in text or ";" not in text:
        return await update.message.reply_text(
            "Usage: /createpoll Question? Option1;Option2;Option3"
        )
    question, opts = text.split("?", 1)
    options = [opt.strip() for opt in opts.split(";") if opt.strip()]
    if len(options) < 2:
        return await update.message.reply_text("Provide at least 2 options.")
    poll_message = await update.message.reply_poll(
        question.strip() + "?",
        options,
        is_anonymous=False,
        allows_multiple_answers=False,
    )
    # Store poll_id in context so we can filter answers
        # ensure we have a dict for active polls
    if "active_polls" not in context.bot_data:
        context.bot_data["active_polls"] = set()

    # store this poll’s ID globally
    context.bot_data["active_polls"].add(poll_message.poll.id)


async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    pid = update.poll_answer.poll_id
    uid = update.poll_answer.user.id
    # Only award points for polls we created
    active = context.bot_data.get("active_polls", set())
    if pid not in active:
        return

    # If they haven't answered this poll before, give them points
    if not has_answered(pid, uid):
        mark_answered(pid, uid)
        add_point(uid, update.poll_answer.user.username or update.poll_answer.user.first_name)
        logger.info(f"Awarded {POINTS_PER_POLL} point to {uid}")
    else:
        logger.debug(f"User {uid} already answered poll {pid}")

async def score(update: Update, _: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT points FROM user_points WHERE user_id = ?", (uid,))
    row = c.fetchone()
    conn.close()
    pts = row[0] if row else 0
    await update.message.reply_text(f"You have {pts} point(s).")

async def leaderboard(update: Update, _: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT username, points FROM user_points ORDER BY points DESC LIMIT 10")
    top = c.fetchall()
    conn.close()
    text = "\n".join(f"{i+1}. {u}: {p}" for i, (u, p) in enumerate(top))
    await update.message.reply_text(f"🏆 Top Participants:\n\n{text}")

async def whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Usage: /whitelist 5
    try:
        threshold = int(context.args[0])
    except:
        return await update.message.reply_text("Usage: /whitelist <min_points>")
        conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT user_id, username FROM user_points WHERE points >= ? ORDER BY points DESC",
        (threshold,),
    )
    rows = c.fetchall()  # list of (user_id, username)
    conn.close()

    if not rows:
        return await update.message.reply_text("No users meet that threshold yet.")

    # Build safe HTML mentions without the leading "@"
    mentions = [mention_html(uid, uname) for uid, uname in rows]
    text = "✅ Whitelisted Users:\n" + "\n".join(mentions)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# --- Main entrypoint ---
def main():
    init_db()
    token = os.getenv("BOT_TOKEN")
    app = ApplicationBuilder().token(token).build()

    # register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("createpoll", createpoll))
    app.add_handler(PollAnswerHandler(handle_poll_answer))
    app.add_handler(CommandHandler("score", score))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("whitelist", whitelist))

    logger.info(f"Starting {BOT_NAME}…")
    app.run_polling()

if __name__ == "__main__":
    main()
