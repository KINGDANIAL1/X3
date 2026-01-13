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
    Updater, MessageHandler, Filters, CommandHandler, CallbackContext,
    CallbackQueryHandler
)

# ============ تهيئة المتغيرات للعمل على Railway ============
# على Railway، يتم تمرير التوكن عبر متغير البيئة
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# للمشرفين - يمكن إضافة معرفاتهم عبر متغير البيئة
ADMIN_IDS = os.environ.get("ADMIN_IDS", "")
ADMIN_USERS = []
if ADMIN_IDS:
    try:
        ADMIN_USERS = [int(id.strip()) for id in ADMIN_IDS.split(",")]
    except:
        ADMIN_USERS = []

# إعدادات أخرى
PORT = int(os.environ.get("PORT", 8443))  # Railway يستخدم PORT
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")  # رابط Webhook إذا كان موجود

# ============ هياكل البيانات ============
TASK_HISTORY_SIZE = 100  # زيادة سعة التاريخ

class Task:
    """فئة تمثل مهمة تنفيذ كود"""
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
        """تحويل المهمة إلى قاموس"""
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
    """البوت الرئيسي مع إدارة المهام"""
    
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
        """إضافة مهمة جديدة للتنفيذ"""
        task_id = f"task_{int(time.time())}_{user_id}_{hash(code) % 10000}"
        task = Task(task_id, user_id, code)
        task.username = username
        task.start_time = datetime.now()
        task.status = "pending"
        
        self.tasks[task_id] = task
        self.task_queue.put(task)
        self.user_stats[user_id]['tasks'] += 1
        self.system_stats['total_tasks'] += 1
        
        return task_id
    
    def _task_worker(self):
        """العامل الذي ينفذ المهام من الطابور"""
        while self.is_running:
            try:
                task = self.task_queue.get(timeout=1)
                self._execute_task(task)
                
                # تحديث التاريخ
                self.task_history.append(task)
                if len(self.task_history) > TASK_HISTORY_SIZE:
                    self.task_history.pop(0)
                    
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Error in task worker: {e}")
    
    def _execute_task(self, task: Task):
        """تنفيذ مهمة محددة"""
        task.status = "running"
        
        # حفظ الكود في ملف مؤقت
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(task.code)
            script_path = f.name
        
        try:
            start_time = time.time()
            result = subprocess.run(
                [os.sys.executable, script_path],
                capture_output=True,
                text=True,
                timeout=60,  # زيادة وقت التنفيذ إلى 60 ثانية
                encoding='utf-8',
                errors='ignore'
            )
            execution_time = time.time() - start_time
            
            task.execution_time = execution_time
            task.output = result.stdout
            task.error = result.stderr
            task.status = "completed" if result.returncode == 0 else "failed"
            task.end_time = datetime.now()
            
            if task.status == "completed":
                self.user_stats[task.user_id]['success'] += 1
                self.system_stats['successful_tasks'] += 1
            else:
                self.user_stats[task.user_id]['errors'] += 1
                self.system_stats['failed_tasks'] += 1
            
        except subprocess.TimeoutExpired:
            task.status = "failed"
            task.error = "⏱️ انتهى وقت التنفيذ (60 ثانية كحد أقصى)"
            task.end_time = datetime.now()
            
            self.user_stats[task.user_id]['errors'] += 1
            self.system_stats['failed_tasks'] += 1
            
        except Exception as e:
            task.status = "failed"
            task.error = f"❌ خطأ أثناء التنفيذ:\n{str(e)}"
            task.end_time = datetime.now()
            
            self.user_stats[task.user_id]['errors'] += 1
            self.system_stats['failed_tasks'] += 1
            
        finally:
            try:
                os.remove(script_path)
            except:
                pass
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """الحصول على مهمة بواسطة المعرف"""
        return self.tasks.get(task_id)
    
    def get_user_tasks(self, user_id: int) -> List[Task]:
        """الحصول على مهام مستخدم معين"""
        return [task for task in self.task_history if task.user_id == user_id][-10:]  # آخر 10 مهام
    
    def get_recent_tasks(self, limit: int = 5) -> List[Task]:
        """الحصول على أحدث المهام"""
        return list(reversed(self.task_history[-limit:]))

# إنشاء نسخة من البوت
bot = CodeExecutorBot()

# ============ دوال المعالجة للتيليجرام ============

def start(update: Update, context: CallbackContext):
    """معالج أمر /start"""
    user = update.effective_user
    
    keyboard = [
        [InlineKeyboardButton("🚀 تشغيل كود جديد", callback_data='new_code')],
        [InlineKeyboardButton("📋 مهامي الأخيرة", callback_data='my_tasks')],
        [InlineKeyboardButton("❓ المساعدة", callback_data='help')],
    ]
    
    # إضافة لوحة التحكم للمشرفين
    if user.id in ADMIN_USERS:
        keyboard.append([InlineKeyboardButton("⚙️ لوحة التحكم", callback_data='dashboard')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # استخدام reply_text بأمان
    update.message.reply_text(
        f"👋 مرحباً {user.first_name}!\n"
        "🤖 بوت تنفيذ كود Python\n"
        "🚀 يعمل على Railway\n"
        "⚡ بدون قيود تقريباً\n\n"
        "📌 **مميزات:**\n"
        "• وقت تنفيذ 60 ثانية\n"
        "• دعم مكتبات Python\n"
        "• تشغيل متعدد المهام\n\n"
        "اختر أحد الخيارات:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

def handle_code_input(update: Update, context: CallbackContext):
    """معالجة إدخال الكود"""
    user = update.effective_user
    code = update.message.text
    
    # تجاهل الأوامر
    if code.startswith('/'):
        return
    
    # إذا كان الكود محاطًا بعلامات ```
    if code.startswith('```') and code.endswith('```'):
        code = code[3:-3].strip()
        if code.lower().startswith('python'):
            code = code[6:].strip()
    
    # التحقق من طول الكود
    if len(code) > 5000:
        update.message.reply_text("⚠️ الكود طويل جداً. الحد الأقصى 5000 حرف.")
        return
    
    # إضافة المهمة للطابور
    task_id = bot.add_task(user.id, user.username or user.first_name, code)
    
    # إرسال رسالة تأكيد
    update.message.reply_text(
        f"✅ **تم إضافة المهمة للتنفيذ**\n\n"
        f"🆔 **معرف المهمة:** `{task_id}`\n"
        f"👤 **المستخدم:** {user.first_name}\n"
        f"📝 **طول الكود:** {len(code)} حرف\n"
        f"⏳ **الحالة:** قيد التنفيذ...\n\n"
        f"📊 **لمتابعة الحالة:**\n"
        f"`/status {task_id}`",
        parse_mode='Markdown'
    )

def status_command(update: Update, context: CallbackContext):
    """عرض حالة مهمة معينة"""
    user = update.effective_user
    
    if not context.args:
        update.message.reply_text(
            "⚠️ **يرجى تحديد معرف المهمة**\n\n"
            "📌 **طريقة الاستخدام:**\n"
            "`/status task_1234567890`\n\n"
            "📋 **لعرض مهامك:**\n"
            "`/mytasks`",
            parse_mode='Markdown'
        )
        return
    
    task_id = context.args[0]
    task = bot.get_task(task_id)
    
    if not task:
        update.message.reply_text(
            "❌ **لم يتم العثور على المهمة**\n\n"
            "⚠️ **الأسباب المحتملة:**\n"
            "• المعرف غير صحيح\n"
            "• المهمة انتهت منذ أكثر من ساعة\n"
            "• تم تنظيف المهام القديمة",
            parse_mode='Markdown'
        )
        return
    
    # التحقق من الصلاحيات
    if task.user_id != user.id and user.id not in ADMIN_USERS:
        update.message.reply_text("⛔ ليس لديك صلاحية عرض هذه المهمة")
        return
    
    status_icons = {
        'pending': '⏳',
        'running': '🔄',
        'completed': '✅',
        'failed': '❌'
    }
    
    status_text = f"""
📋 **معلومات المهمة**

🆔 **المعرف:** `{task.id}`
👤 **المستخدم:** {task.username}
📅 **وقت البدء:** {task.start_time.strftime('%Y-%m-%d %H:%M:%S') if task.start_time else 'N/A'}
📊 **الحالة:** {status_icons.get(task.status, '❓')} {task.status}
⏱️ **زمن التنفيذ:** {task.execution_time:.2f} ثانية
📝 **طول الكود:** {len(task.code)} حرف
"""
    
    if task.status == 'completed':
        if task.output:
            output_preview = task.output[:500] + ("..." if len(task.output) > 500 else "")
            status_text += f"\n📤 **المخرجات:**\n```\n{output_preview}\n```"
        else:
            status_text += "\n✅ **تم التنفيذ بدون مخرجات**"
    
    elif task.status == 'failed':
        if task.error:
            error_preview = task.error[:500] + ("..." if len(task.error) > 500 else "")
            status_text += f"\n❌ **الخطأ:**\n```\n{error_preview}\n```"
    
    # إضافة أزرار للتحكم
    keyboard = []
    if user.id == task.user_id or user.id in ADMIN_USERS:
        keyboard.append([InlineKeyboardButton("🔄 تحديث الحالة", callback_data=f'status_{task_id}')])
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    update.message.reply_text(status_text, parse_mode='Markdown', reply_markup=reply_markup)

def my_tasks_command(update: Update, context: CallbackContext):
    """عرض مهام المستخدم الأخيرة"""
    # تحديد مصدر الرسالة (من رسالة عادية أو callback query)
    if update.message:
        # الحالة العادية: من أمر /mytasks
        chat_id = update.message.chat_id
        reply_method = update.message.reply_text
        can_edit = False
    elif update.callback_query:
        # الحالة: من ضغط زر
        query = update.callback_query
        chat_id = query.message.chat_id
        reply_method = query.edit_message_text
        can_edit = True
        query.answer()
    else:
        return
    
    user = update.effective_user
    user_tasks = bot.get_user_tasks(user.id)
    
    if not user_tasks:
        reply_method("📭 **لم تقم بتنفيذ أي مهام بعد**\n\n"
                    "🚀 **لبدء التنفيذ:**\n"
                    "1. أرسل كود Python مباشرة\n"
                    "2. أو اضغط على 'تشغيل كود جديد'",
                    parse_mode='Markdown')
        return
    
    tasks_text = "📋 **آخر 10 مهام لك:**\n\n"
    
    for i, task in enumerate(reversed(user_tasks), 1):
        status_icon = '✅' if task.status == 'completed' else '❌' if task.status == 'failed' else '⏳'
        time_str = task.start_time.strftime('%H:%M') if task.start_time else 'N/A'
        
        # عرض جزء من الكود
        code_preview = task.code[:40] + "..." if len(task.code) > 40 else task.code
        tasks_text += f"{i}. {status_icon} **{task.status}**\n"
        tasks_text += f"   🆔 `{task.id}`\n"
        tasks_text += f"   📝 {code_preview}\n"
        tasks_text += f"   🕐 {time_str} | ⏱️ {task.execution_time:.2f}s\n\n"
    
    # إضافة زر لتحديث القائمة
    keyboard = [
        [InlineKeyboardButton("🔄 تحديث القائمة", callback_data='my_tasks'),
         InlineKeyboardButton("🚀 كود جديد", callback_data='new_code')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if can_edit:
        reply_method(text=tasks_text, parse_mode='Markdown', reply_markup=reply_markup)
    else:
        reply_method(tasks_text, parse_mode='Markdown', reply_markup=reply_markup)

def dashboard_command(update: Update, context: CallbackContext):
    """لوحة التحكم للمشرفين"""
    # تحديد مصدر الرسالة
    if update.message:
        reply_method = update.message.reply_text
        can_edit = False
    elif update.callback_query:
        query = update.callback_query
        reply_method = query.edit_message_text
        can_edit = True
        query.answer()
    else:
        return
    
    user = update.effective_user
    
    if user.id not in ADMIN_USERS:
        error_msg = "⛔ ليس لديك صلاحية الوصول إلى لوحة التحكم"
        if can_edit:
            reply_method(text=error_msg)
        else:
            update.message.reply_text(error_msg)
        return
    
    system_stats = bot.system_stats
    recent_tasks = bot.get_recent_tasks(5)
    
    # حساب متوسط وقت التنفيذ
    avg_time = system_stats['total_execution_time'] / system_stats['total_tasks'] if system_stats['total_tasks'] > 0 else 0
    
    dashboard_text = f"""
⚙️ **لوحة تحكم المشرف**
🚀 **يعمل على Railway**

📊 **إحصائيات النظام:**
• 🔢 **إجمالي المهام:** {system_stats['total_tasks']}
• ✅ **ناجحة:** {system_stats['successful_tasks']}
• ❌ **فاشلة:** {system_stats['failed_tasks']}
• ⏱️ **متوسط الوقت:** {avg_time:.2f} ثانية

👥 **المستخدمون النشطون:** {len(bot.user_stats)}
📋 **آخر 5 مهام:**
"""
    
    for task in recent_tasks:
        status_icon = '✅' if task.status == 'completed' else '❌' if task.status == 'failed' else '⏳'
        time_str = task.start_time.strftime('%H:%M') if task.start_time else 'N/A'
        dashboard_text += f"{status_icon} **{task.username}** ({time_str}): {task.code[:25]}...\n"
    
    keyboard = [
        [InlineKeyboardButton("🔄 تحديث", callback_data='refresh_dashboard'),
         InlineKeyboardButton("🗑️ تنظيف", callback_data='cleanup')],
        [InlineKeyboardButton("📊 إحصائيات كاملة", callback_data='full_stats')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if can_edit:
        reply_method(text=dashboard_text, parse_mode='Markdown', reply_markup=reply_markup)
    else:
        reply_method(dashboard_text, parse_mode='Markdown', reply_markup=reply_markup)

def help_command(update: Update, context: CallbackContext):
    """عرض المساعدة"""
    help_text = """
📚 **مساعدة بوت تنفيذ الكود**

🤖 **الأوامر المتاحة:**
/start - بدء البوت وعرض القائمة
/help - عرض هذه الرسالة
/status <task_id> - عرض حالة مهمة
/mytasks - عرض مهامي الأخيرة
/dashboard - لوحة التحكم (للمشرفين فقط)

🚀 **كيفية الاستخدام:**
1. أرسل كود Python مباشرة
2. أو استخدم علامات ``` للكود الطويل
3. انتظر تنفيذ المهمة
4. تابع حالة المهمة بـ /status

💡 **أمثلة:**
