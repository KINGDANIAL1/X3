#!/usr/bin/env python3
import os
import tempfile
import subprocess
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

# ======================== الوظائف ========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 بوت تنفيذ Python\n\n"
        "📌 أرسل كود Python مباشرة\n"
        "📌 أو أرسل ملف .py\n\n"
        "أوامر:\n"
        "/run → إعادة تنفيذ آخر كود\n"
        "/clear → مسح الذاكرة"
    )

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("🧹 تم مسح الذاكرة")

def run_code(code: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(code)
        path = f.name

    try:
        # تعديل الوقت ليصل إلى 24 ساعة
        result = subprocess.run(
            ["python3", path],
            capture_output=True,
            text=True,
            timeout=24*60*60  # 86400 ثانية = 24 ساعة
        )
        output = (result.stdout or "") + (result.stderr or "")
        return output or "✅ تم التنفيذ بدون مخرجات"
    except subprocess.TimeoutExpired:
        return "⏱️ انتهى وقت التنفيذ"
    finally:
        os.remove(path)

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

    file = await doc.get_file()
    code = (await file.download_as_bytearray()).decode()

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
    await update.message.reply_text(f"🔁 إعادة التنفيذ:\n{output}")

# ======================== البداية ========================

def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN غير موجود")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # إضافة الأوامر والمعالجات
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("run", run_last))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))

    # تشغيل البوت
    app.run_polling()

if __name__ == "__main__":
    main()
