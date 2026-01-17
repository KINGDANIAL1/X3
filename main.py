#!/usr/bin/env python3
import os
import tempfile
from multiprocessing import Process, Queue
from telegram import Update, Document
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CODE_TIMEOUT = 60
MAX_OUTPUT = 40000

# ======================== KERNEL EXECUTOR ========================

def worker(code: str, q: Queue):
    import subprocess
    import os
    import tempfile

    try:
        # ---------- LINUX MODE ----------
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
        q.put(f"❌ خطأ: {e}")
    finally:
        try:
            if 'path' in locals() and os.path.exists(path):
                os.remove(path)
        except:
            pass

def run_code(code: str) -> str:
    q = Queue()
    p = Process(target=worker, args=(code, q))
    p.start()
    p.join(CODE_TIMEOUT + 5)

    if p.is_alive():
        p.terminate()
        return "⏱️ انتهى وقت التنفيذ"

    try:
        return q.get()
    except:
        return "❌ فشل استرجاع المخرجات"

# ======================== TELEGRAM HANDLERS ========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Execution Bot\n\n"
        "• Python: أرسل الكود مباشرة\n"
        "• Linux: ابدأ بـ !\n\n"
        "أمثلة:\n"
        "!ls -la\n"
        "!whoami\n\n"
        "/run → إعادة التنفيذ\n"
        "/clear → مسح الذاكرة"
    )

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("🧹 تم مسح الذاكرة")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text
    context.user_data["last_code"] = code

    output = run_code(code)
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + "\n... (تم القطع)"

    await update.message.reply_text(f"📤 النتيجة:\n{output}")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc: Document = update.message.document

    if not doc.file_name.endswith(".py"):
        await update.message.reply_text("❌ فقط ملفات .py")
        return

    if doc.file_size > 5_000_000:
        await update.message.reply_text("❌ الملف كبير جدًا")
        return

    file = await doc.get_file()
    code = (await file.download_as_bytearray()).decode(errors="ignore")

    context.user_data["last_code"] = code
    output = run_code(code)

    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + "\n... (تم القطع)"

    await update.message.reply_text(f"📤 النتيجة:\n{output}")

async def run_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = context.user_data.get("last_code")
    if not code:
        await update.message.reply_text("❌ لا يوجد كود محفوظ")
        return

    output = run_code(code)
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + "\n... (تم القطع)"

    await update.message.reply_text(f"🔁 إعادة التنفيذ:\n{output}")

# ======================== BOOT ========================

def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN غير موجود")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("run", run_last))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))

    app.run_polling()

if __name__ == "__main__":
    main()
