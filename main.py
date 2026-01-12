#!/usr/bin/env python3
import os
import tempfile
import subprocess
from telegram import Update
from telegram.ext import Updater, MessageHandler, Filters, CommandHandler, CallbackContext

# ضع توكن بوتك هنا أو عبر متغير بيئة
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # أو ضع "توكنك هنا"

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "🤖 بوت تنفيذ بايثون جاهز!\n"
        "أرسل أي كود Python وسيتم تشغيله."
    )

def execute_code(update: Update, context: CallbackContext):
    code = update.message.text

    # حفظ الكود في ملف مؤقت
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        script_path = f.name

    try:
        # تشغيل السكربت باستخدام subprocess
        result = subprocess.run(
            [os.sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=300  # 5 دقائق كحد أقصى
        )
        output = (result.stdout or "") + (result.stderr or "")
        if not output.strip():
            output = "✅ تم التنفيذ بدون مخرجات"
    except subprocess.TimeoutExpired:
        output = "⏱️ انتهى الوقت (Timeout)"
    except Exception as e:
        output = f"❌ خطأ أثناء التنفيذ:\n{e}"
    finally:
        os.remove(script_path)

    # قص المخرجات إذا كانت طويلة جداً
    if len(output) > 4000:
        output = output[:4000] + "\n... (تم القطع)"

    update.message.reply_text(f"📤 النتيجة:\n{output}")

def main():
    updater = Updater(BOT_TOKEN)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, execute_code))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ يرجى وضع توكن البوت في متغير البيئة BOT_TOKEN")
    else:
        main()
