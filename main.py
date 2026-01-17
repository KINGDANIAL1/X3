#!/usr/bin/env python3
import os
import tempfile
import logging
from multiprocessing import Process, Queue
from telegram import Update, Document
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ======================== CONFIG ========================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CODE_TIMEOUT = 60
MAX_OUTPUT = 40000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ======================== EXECUTOR ========================

def worker(code: str, q: Queue):
    import subprocess
    import os
    import tempfile

    path = None
    try:
        # ---------- SHELL MODE ----------
        if code.startswith("!"):
            cmd = code[1:].strip()
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=CODE_TIMEOUT
            )
            output = (result.stdout or "") + (result.stderr or "")
            q.put(output.strip() or "✅ تم التنفيذ بدون مخرجات")
            return

        # ---------- PYTHON MODE ----------
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(code)
            path = f.name

        result = subprocess.run(
            ["python3", path],
            capture_output=True,
            text=True,
            timeout=CODE_TIMEOUT
        )

        output = (result.stdout or "") + (result.stderr or "")
        q.put(output.strip() or "✅ تم التنفيذ بدون مخرجات")

    except subprocess.TimeoutExpired:
        q.put("⏱️ انتهى وقت التنفيذ")
    except Exception as e:
        q.put(f"❌ Exception: {e}")
    finally:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception as e:
            q.put(f"⚠️ Cleanup error: {e}")

def run_code(code: str) -> str:
    q = Queue()
    p = Process(target=worker, args=(code, q))
    p.start()
    p.join(CODE_TIMEOUT + 5)

    if p.is_alive():
        p.terminate()
        return "⏱️ العملية لم تنتهِ وتم إيقافها قسريًا"

    try:
        return q.get(timeout=5)
    except Exception as e:
        logging.error(f"Queue error: {e}")
        return "❌ فشل استرجاع المخرجات"

# ======================== SAFE REPLY ========================

async def safe_reply(update: Update, text: str):
    try:
        await update.message.reply_text(text)
    except Exception as e:
        logging.error(f"Telegram send error: {e}")

# ======================== HANDLERS ========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_reply(
        update,
        "🤖 Execution Bot\n\n"
        "• Python: أرسل الكود مباشرة\n"
        "• Shell: ابدأ بـ !\n\n"
        "أمثلة:\n"
        "!id\n"
        "!uname -a\n\n"
        "/run → إعادة آخر تنفيذ\n"
        "/clear → مسح الذاكرة"
    )

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await safe_reply(update, "🧹 تم مسح الذاكرة")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text
    context.user_data["last_code"] = code

    output = run_code(code)
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + "\n... (تم القطع)"

    await safe_reply(update, f"📤 النتيجة:\n{output}")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc: Document = update.message.document

    try:
        if not doc.file_name.endswith(".py"):
            await safe_reply(update, "❌ فقط ملفات .py")
            return

        if doc.file_size > 5_000_000:
            await safe_reply(update, "❌ الملف أكبر من 5MB")
            return

        file = await doc.get_file()
        code = (await file.download_as_bytearray()).decode("utf-8", errors="ignore")

        context.user_data["last_code"] = code
        output = run_code(code)

        if len(output) > MAX_OUTPUT:
            output = output[:MAX_OUTPUT] + "\n... (تم القطع)"

        await safe_reply(update, f"📤 النتيجة:\n{output}")

    except Exception as e:
        logging.exception("File handling crash")
        await safe_reply(update, f"❌ File error: {e}")

async def run_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = context.user_data.get("last_code")

    if not code:
        await safe_reply(update, "❌ لا يوجد كود محفوظ")
        return

    output = run_code(code)
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + "\n... (تم القطع)"

    await safe_reply(update, f"🔁 إعادة التنفيذ:\n{output}")

# ======================== BOOT ========================

def main():
    if not BOT_TOKEN:
        logging.error("BOT_TOKEN غير موجود")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("run", run_last))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))

    logging.info("🔥 Bot is running (NO RESTRICTIONS MODE)")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
