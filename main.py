#!/usr/bin/env python3
import os
import tempfile
import subprocess
import re
import time
import json
import threading
import queue
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    CommandHandler,
    CallbackContext,
    CallbackQueryHandler
)

# ============================================
#               تهيئة المتغيرات
# ============================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = os.environ.get("ADMIN_IDS", "")
ADMIN_USERS = [int(x.strip()) for x in ADMIN_IDS.split(",")] if ADMIN_IDS else []

PORT = int(os.environ.get("PORT", 8443))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")

# ============================================
#               هياكل البيانات
# ============================================

TASK_HISTORY_SIZE = 100

class Task:
    def __init__(self, task_id: str, user_id: int, code: str):
        self.id = task_id
        self.user_id = user_id
        self.username = ""
        self.code = code
        self.status = "pending"
        self.result = ""
        self.start_time = None
        self.end_time = None
        self.execution_time = 0
        self.output = ""
        self.error = ""

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'username': self.username,
            'code': self.code[:50] + "..." if len(self.code) > 50 else self.code,
            'status': self.status,
            'start_time': str(self.start_time) if self.start_time else None,
            'end_time': str(self.end_time) if self.end_time else None,
            'execution_time': self.execution_time,
            'has_output': bool(self.output),
            'has_error': bool(self.error)
        }

class CodeExecutorBot:
    def __init__(self):
        self.task_queue = queue.Queue()
        self.tasks: Dict[str, Task] = {}
        self.task_history: List[Task] = []
        self.user_stats = defaultdict(lambda: {'tasks': 0, 'success': 0, 'errors': 0})
        self.system_stats = {
            'total_tasks': 0,
            'successful_tasks': 0,
            'failed_tasks': 0,
            'total_execution_time': 0
        }
        self.is_running = True
        self.worker_thread = threading.Thread(target=self._task_worker, daemon=True)
        self.worker_thread.start()

    def add_task(self, user_id: int, username: str, code: str) -> str:
        task_id = f"task_{int(time.time())}_{user_id}_{hash(code) % 10000}"
        task = Task(task_id, user_id, code)
        task.username = username
        task.start_time = datetime.now()
        self.tasks[task_id] = task
        self.task_queue.put(task)
        self.user_stats[user_id]['tasks'] += 1
        self.system_stats['total_tasks'] += 1
        return task_id

    def _task_worker(self):
        while self.is_running:
            try:
                task = self.task_queue.get(timeout=1)
                self._execute_task(task)
                self.task_history.append(task)
                if len(self.task_history) > TASK_HISTORY_SIZE:
                    self.task_history.pop(0)
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Worker error: {e}")

    def _execute_task(self, task: Task):
        task.status = "running"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(task.code)
            script_path = f.name

        try:
            start = time.time()
            result = subprocess.run(
                [os.sys.executable, "-u", script_path],
                capture_output=True,
                text=True,
                timeout=60,
                encoding='utf-8',
                errors='replace'
            )
            task.execution_time = time.time() - start
            task.output = result.stdout
            task.error = result.stderr
            task.status = "completed" if result.returncode == 0 else "failed"

        except subprocess.TimeoutExpired:
            task.status = "failed"
            task.error = "انتهى وقت التنفيذ (الحد الأقصى 60 ثانية)"
        except Exception as e:
            task.status = "failed"
            task.error = f"خطأ أثناء التنفيذ:\n{str(e)}"
        finally:
            try:
                os.unlink(script_path)
            except:
                pass

    def get_task(self, task_id: str) -> Optional[Task]:
        return self.tasks.get(task_id)

    def get_user_tasks(self, user_id: int) -> List[Task]:
        return [t for t in self.task_history if t.user_id == user_id][-10:]

# ============================================
#                 البوت نفسه
# ============================================

bot_instance = CodeExecutorBot()

# ============================================
#              دوال المعالجات
# ============================================

async def start(update: Update, context: CallbackContext):
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton("🚀 تشغيل كود جديد", callback_data='new_code')],
        [InlineKeyboardButton("📋 مهامي الأخيرة", callback_data='my_tasks')],
        [InlineKeyboardButton("❓ المساعدة", callback_data='help')],
    ]
    if user.id in ADMIN_USERS:
        keyboard.append([InlineKeyboardButton("⚙️ لوحة التحكم", callback_data='dashboard')])

    await update.message.reply_text(
        f"👋 مرحباً {user.first_name}!\n"
        "هذا بوت لتشغيل أكواد Python\n\n"
        "اكتب الكود مباشرة أو استخدم ```python\nالكود هنا\n```",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_code(update: Update, context: CallbackContext):
    if update.message.text.startswith('/'):
        return

    code = update.message.text.strip()
    if code.startswith('```') and code.endswith('```'):
        code = code.strip('`').strip()
        if code.lower().startswith('python'):
            code = code[6:].strip()

    if len(code) > 8000:
        await update.message.reply_text("الكود طويل جداً (الحد الأقصى ~8000 حرف)")
        return

    task_id = bot_instance.add_task(
        update.effective_user.id,
        update.effective_user.username or update.effective_user.first_name,
        code
    )

    await update.message.reply_text(
        f"تم إضافة المهمة #{task_id}\n"
        "سيتم تنفيذ الكود قريباً...\n\n"
        f"للمتابعة: /status {task_id}"
    )

async def status(update: Update, context: CallbackContext):
    if not context.args:
        await update.message.reply_text("استخدام: /status <task_id>")
        return

    task_id = context.args[0]
    task = bot_instance.get_task(task_id)

    if not task:
        await update.message.reply_text("لم يتم العثور على هذه المهمة")
        return

    lines = [
        f"🆔 المهمة: {task.id}",
        f"الحالة: {task.status}",
        f"المستخدم: {task.username}",
        f"الوقت: {task.execution_time:.2f} ثانية"
    ]

    if task.output:
        lines.append("\nالمخرجات:")
        lines.append("----------------------------------------")
        lines.append(task.output.rstrip())
        lines.append("----------------------------------------")

    if task.error:
        lines.append("\nالأخطاء:")
        lines.append("----------------------------------------")
        lines.append(task.error.rstrip())
        lines.append("----------------------------------------")

    # الطريقة الأكثر أماناً: بدون parse_mode
    await update.message.reply_text("\n".join(lines))

# يمكنك إكمال باقي الدوال (my_tasks, dashboard, buttons...) بنفس الطريقة
# أهم شيء: عند عرض output أو error → لا تستخدم parse_mode='Markdown'

# ============================================
#                   التشغيل
# ============================================

async def main():
    if not BOT_TOKEN:
        print("خطأ: لم يتم العثور على BOT_TOKEN")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))

    # أضف باقي الهاندلرز هنا...

    print("البوت يبدأ التشغيل...")
    await application.initialize()

    if WEBHOOK_URL:
        await application.start_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
        )
    else:
        await application.start()
        await application.updater.start_polling(
            drop_pending_updates=True,
            timeout=30
        )

    await application.updater.idle()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
