#!/usr/bin/env python3
import os
import tempfile
import asyncio
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
MAX_OUTPUT = 40000
CODE_TIMEOUT = 60  # ثواني لكل كود

# ======================== تنفيذ الكود في Process ========================

def worker(code: str, q: Queue):
    import subprocess
    import os
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(code)
        path = f.name

    try:
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
        q.put(f"❌ خطأ أثناء التنفيذ: {e}")
    finally:
        os.remove(path)

async def run_code(code: str) -> str:
    q = Queue()
    p = Process(target=worker, args=(code, q))
    p.start()

    # انتظر انتهاء العملية مع timeout buffer
    p.join(CODE_TIMEOUT + 5)
    if p.is_alive():
        p.terminate()
        return "⏱️ انتهى وقت التنفيذ"

    try:
        return q.get() or "✅ تم التنفيذ بدون مخرجات"
    except Exception:
        return "❌ فشل استرجاع المخرجات"

# ======================== Handlers ========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 بوت تنفيذ Python\n\n"
        "📌 أرسل كود Python مباشرة\n"
        "📌 أو أرسل ملف .py\n\n"
        "أوامر:\n"
        "/clear → مسح الذاكرة (إذا وجدت)"
    )

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("🧹 تم مسح الذاكرة")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text

    output = await run_code(code)
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + "\n... (تم القطع)"

    await update.message.reply_text(f"📤 النتيجة:\n{output}")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc: Document = update.message.document
    if not doc.file_name.endswith(".py"):
        await update.message.reply_text("❌ فقط ملفات .py")
        return

    if doc.file_size > 5_000_000:  # 5 ميغا كحد أقصى
        await update.message.reply_text("❌ الملف كبير جدًا")
        return

    try:
        file = await doc.get_file()
        code_bytes = await file.download_as_bytearray()
        code = code_bytes.decode(errors="ignore")
    except Exception:
        await update.message.reply_text("❌ فشل قراءة الملف")
        return

    output = await run_code(code)
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + "\n... (تم القطع)"

    await update.message.reply_text(f"📤 النتيجة:\n{output}")

# ======================== البداية ========================

def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN غير موجود")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # إضافة الأوامر والمعالجات
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))

    # تشغيل البوت
    app.run_polling()

if __name__ == "__main__":
    main()        output = output[:MAX_OUTPUT] + "\n... (تم القطع)"

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
