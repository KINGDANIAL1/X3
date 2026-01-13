#!/usr/bin/env python3
import osت
import tempfile
import subprocess
from telegram import Update
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
MAX_OUTPUT = 4000

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "🤖 بوت تنفيذ Python\n\n"
        "📌 أرسل كود Python مباشرة\n"
        "📌 أو أرسل ملف .py\n\n"
        "أوامر:\n"
        "/run → إعادة تنفيذ آخر كود\n"
        "/clear → مسح الذاكرة"
    )

def clear(update: Update, context: CallbackContext):
    context.user_data.clear()
    update.message.reply_text("🧹 تم مسح الذاكرة")

def run_code(code: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(code)
        path = f.name

    try:
        result = subprocess.run(
            ["python3", path],
            capture_output=True,
            text=True,
            timeout=300
        )
        output = (result.stdout or "") + (result.stderr or "")
        return output or "✅ تم التنفيذ بدون مخرجات"
    except subprocess.TimeoutExpired:
        return "⏱️ انتهى وقت التنفيذ"
    finally:
        os.remove(path)

def handle_text(update: Update, context: CallbackContext):
    code = update.message.text
    context.user_data["last_code"] = code

    output = run_code(code)
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + "\n... (تم القطع)"

    update.message.reply_text(f"📤 النتيجة:\n{output}")

def handle_file(update: Update, context: CallbackContext):
    doc = update.message.document
    if not doc.file_name.endswith(".py"):
        update.message.reply_text("❌ فقط ملفات .py")
        return

    file = doc.get_file()
    code = file.download_as_bytearray().decode()

    context.user_data["last_code"] = code
    output = run_code(code)

    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + "\n... (تم القطع)"

    update.message.reply_text(f"📤 النتيجة:\n{output}")

def run_last(update: Update, context: CallbackContext):
    code = context.user_data.get("last_code")
    if not code:
        update.message.reply_text("❌ لا يوجد كود محفوظ")
        return

    output = run_code(code)
    update.message.reply_text(f"🔁 إعادة التنفيذ:\n{output}")

def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN غير موجود")
        return

    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("clear", clear))
    dp.add_handler(CommandHandler("run", run_last))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))
    dp.add_handler(MessageHandler(Filters.document, handle_file))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
