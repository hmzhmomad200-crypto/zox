import requests
import os
import json
import time
import base64
import copy
import logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from keyboards import main_menu, back_button, admin_menu, channel_menu, subscription_required_keyboard

# ══════════════════════════════════════
#  إعداد السجلات
# ══════════════════════════════════════
import sys
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger(__name__)

# ══════════════════════════════════════
#  متغيرات البيئة
# ══════════════════════════════════════
BOT_TOKEN    = os.getenv("BOT_TOKEN",    "ضع_توكن_البوت_هنا")
BOT_USERNAME = os.getenv("BOT_USERNAME", "your_bot")
# ══ 6 مفاتيح Groq — كل مفتاح متغير منفصل في Railway ══
# GROQ_API_KEY_1 , GROQ_API_KEY_2 , ... , GROQ_API_KEY_6
GROQ_API_KEYS = [
    os.getenv(f"GROQ_API_KEY_{i}")
    for i in range(1, 101)
]
GROQ_API_KEYS = [k for k in GROQ_API_KEYS if k]  # نزيل الفارغة
if not GROQ_API_KEYS:
    # fallback للمتغير القديم
    _old = os.getenv("GROQ_API_KEY", "ضع_مفتاح_GROQ_هنا")
    GROQ_API_KEYS = [_old]
_groq_index = 0

def _get_groq_key():
    return GROQ_API_KEYS[_groq_index % len(GROQ_API_KEYS)]

def _next_groq_key():
    global _groq_index
    _groq_index = (_groq_index + 1) % len(GROQ_API_KEYS)
    return GROQ_API_KEYS[_groq_index]

ADMINS       = [int(x) for x in os.getenv("ADMINS", "123456789").split(",") if x.strip()]

TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"

# ══════════════════════════════════════
#  إعدادات ثابتة
# ══════════════════════════════════════
SYSTEM_PROMPT = """
أنت مساعد متخصص بالكامل في Python.
- تجاوب فقط عن Python.
- إذا كان السؤال خارج Python قل: (أنا متخصص في Python فقط)
- ساعد في: Flask, Django, APIs, Bots, Automation, Debugging, Web Scraping, OOP
- أصلح الأكواد واشرح الأخطاء.
- استخدم العربية دائمًا.
"""

MAX_HISTORY   = 20
RATE_LIMIT    = 2
MAX_FILE_SIZE = 5 * 1024 * 1024

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

MEMORY_FILE   = f"{DATA_DIR}/user_memory.json"
STATS_FILE    = f"{DATA_DIR}/stats.json"
CHATS_FILE    = f"{DATA_DIR}/bot_chats.json"
BANNED_FILE   = f"{DATA_DIR}/banned_users.json"
CHANNEL_FILE  = f"{DATA_DIR}/required_channel.json"

SUPPORTED_EXT = (
    '.txt', '.py', '.js', '.json',
    '.html', '.css', '.md', '.xml', '.csv'
)

# حالات معلّقة
pending_broadcast       = {}
pending_group_broadcast = {}
pending_ban             = {}
pending_unban           = {}
pending_clear           = {}
pending_addchannel      = {}

# ══════════════════════════════════════
#  حفظ / تحميل JSON
# ══════════════════════════════════════
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"فشل حفظ {path}: {e}")

# ══════════════════════════════════════
#  تحميل البيانات
# ══════════════════════════════════════
user_memory       = {str(k): v for k, v in load_json(MEMORY_FILE, {}).items()}
stats             = load_json(STATS_FILE, {
    "total_users"   : 0,
    "total_messages": 0,
    "total_images"  : 0,
    "total_files"   : 0,
    "dew_used"      : 0,
    "started_at"    : datetime.now(timezone.utc).isoformat()
})
bot_chats         = load_json(CHATS_FILE, {})
banned_users      = set(load_json(BANNED_FILE, []))
user_last_message = {}

# تحميل إعدادات القناة الإجبارية
_channel_data    = load_json(CHANNEL_FILE, {"channel": None})
REQUIRED_CHANNEL = _channel_data.get("channel")  # مثال: "@mychannel"

# ══════════════════════════════════════
#  دوال تيليجرام
# ══════════════════════════════════════
def send_message(chat_id, text, reply_markup=None,
                 parse_mode="Markdown", reply_to=None):
    MAX_LEN = 4096
    chat_id = str(chat_id)
    chunks  = [text[i:i + MAX_LEN] for i in range(0, len(text), MAX_LEN)]
    for idx, chunk in enumerate(chunks):
        payload = {"chat_id": chat_id, "text": chunk, "parse_mode": parse_mode}
        if reply_markup and idx == len(chunks) - 1:
            payload["reply_markup"] = json.dumps(reply_markup)
        if reply_to:
            payload["reply_to_message_id"] = reply_to
        try:
            r = requests.post(f"{TELEGRAM_URL}/sendMessage",
                              data=payload, timeout=15)
            if not r.json().get("ok"):
                payload.pop("parse_mode", None)
                requests.post(f"{TELEGRAM_URL}/sendMessage",
                              data=payload, timeout=15)
        except Exception as e:
            log.error(f"send_message({chat_id}): {e}")


def edit_message(chat_id, message_id, text, reply_markup=None):
    payload = {
        "chat_id"   : str(chat_id),
        "message_id": message_id,
        "text"      : text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        requests.post(f"{TELEGRAM_URL}/editMessageText",
                      data=payload, timeout=15)
    except Exception as e:
        log.error(f"edit_message: {e}")


def answer_callback(cb_id, text="", alert=False):
    try:
        requests.post(f"{TELEGRAM_URL}/answerCallbackQuery",
                      data={"callback_query_id": cb_id,
                            "text": text, "show_alert": alert},
                      timeout=10)
    except Exception:
        pass


def send_typing(chat_id):
    try:
        requests.post(f"{TELEGRAM_URL}/sendChatAction",
                      data={"chat_id": str(chat_id), "action": "typing"},
                      timeout=10)
    except Exception:
        pass




def send_document(chat_id, file_bytes, file_name, caption=""):
    """يرسل ملف للمستخدم"""
    try:
        requests.post(
            f"{TELEGRAM_URL}/sendDocument",
            data={"chat_id": str(chat_id), "caption": caption, "parse_mode": "Markdown"},
            files={"document": (file_name, file_bytes)},
            timeout=30
        )
    except Exception as e:
        log.error(f"send_document: {e}")


def ask_groq_fix(file_text, file_name):
    """
    يطلب من النموذج:
    1. تحليل الأعطال
    2. إرجاع الكود المصلح كاملاً بين ``` ```
    """
    prompt = f"""أنت خبير Python. لديك الملف التالي:

اسم الملف: {file_name}

```
{file_text[:6000]}
```

المطلوب:
1. اذكر الأعطال والمشاكل الموجودة بوضوح (قائمة مرقمة)
2. بعدها أرسل الكود المصلح كاملاً بين ```python و```
لا تحذف أي كود — أرسل الملف كاملاً مصلحاً."""

    messages = [
        {"role": "system", "content": "أنت خبير Python. أجب بالعربية دائماً."},
        {"role": "user",   "content": prompt}
    ]
    attempts = len(GROQ_API_KEYS)
    for _ in range(attempts):
        headers = {
            "Authorization": f"Bearer {_get_groq_key()}",
            "Content-Type" : "application/json"
        }
        data = {
            "model"      : "llama-3.1-8b-instant",
            "messages"   : messages,
            "temperature": 0.2,
            "max_tokens" : 4096
        }
        try:
            r = requests.post(GROQ_URL, headers=headers, json=data, timeout=90)
            if r.status_code in (429, 401):
                log.warning(f"Groq fix key #{_groq_index+1} returned {r.status_code}, switching...")
                _next_groq_key()
                time.sleep(0.5)
                continue
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except requests.exceptions.Timeout:
            return None
        except Exception:
            _next_groq_key()
            continue
    return None


def extract_code_block(text):
    """يستخرج الكود من بين ``` ``` في الرد"""
    import re
    # يحاول ```python ... ``` أو ``` ... ```
    patterns = [
        r"```python\s*([\s\S]+?)```",
        r"```\w*\s*([\s\S]+?)```",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1).strip()
    return None


def handle_file_fix(chat_id, file_content, file_name, reply_to_id=None):
    """
    المنطق الكامل: يحلل الملف، يصلحه، يرسل الشرح + الملف المصلح
    """
    send_typing(chat_id)
    file_text = process_file(file_content, file_name)

    # لو الملف غير نصي
    if "نوع غير مدعوم" in file_text:
        send_message(chat_id,
                     f"❌ نوع الملف `{file_name}` غير مدعوم للتحليل.\nالمدعوم: .py .js .txt .json .html .css .md",
                     reply_to=reply_to_id)
        return

    send_message(chat_id, "🔍 جاري تحليل الملف وإصلاح الأعطال...", reply_to=reply_to_id)
    result = ask_groq_fix(file_text, file_name)

    if not result:
        send_message(chat_id, "❌ فشل التحليل، حاول مرة أخرى", reply_to=reply_to_id)
        return

    fixed_code = extract_code_block(result)

    # إرسال الشرح (نزيل الكود الطويل من الرسالة لتكون نظيفة)
    import re
    explanation = re.sub(r"```[\s\S]*?```", "", result).strip()
    if explanation:
        send_message(chat_id, explanation, reply_to=reply_to_id)

    # إرسال الملف المصلح إن وُجد
    if fixed_code:
        fixed_bytes = fixed_code.encode("utf-8")
        # اسم الملف المصلح
        name_parts = file_name.rsplit(".", 1)
        fixed_name = f"{name_parts[0]}_fixed.{name_parts[1]}" if len(name_parts) == 2 else f"{file_name}_fixed"
        send_document(chat_id, fixed_bytes, fixed_name,
                      caption=f"✅ *الملف المصلح:* `{fixed_name}`")
    else:
        send_message(chat_id,
                     "⚠️ لم يتمكن النموذج من استخراج كود مصلح كامل.\nجرب أرسل الملف مجدداً أو استخدم /dew مع سؤال محدد.",
                     reply_to=reply_to_id)

def get_file(file_id, max_size=MAX_FILE_SIZE):
    try:
        info = requests.get(
            f"{TELEGRAM_URL}/getFile?file_id={file_id}", timeout=10
        ).json()
        if not info.get("ok"):
            return None, "فشل الحصول على معلومات الملف"
        result    = info["result"]
        file_size = result.get("file_size", 0)
        if file_size > max_size:
            mb = max_size // 1024 // 1024
            return None, f"❌ الملف كبير جداً ({file_size // 1024} KB). الحد الأقصى {mb} MB"
        url  = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{result['file_path']}"
        resp = requests.get(url, timeout=30)
        return (resp.content, None) if resp.status_code == 200 \
               else (None, "فشل تحميل الملف من تيليجرام")
    except Exception as e:
        return None, f"خطأ في get_file: {e}"


# ══════════════════════════════════════
#  الاشتراك الإجباري
# ══════════════════════════════════════
def check_subscription(user_id):
    """يتحقق إذا المستخدم مشترك في القناة الإجبارية"""
    if not REQUIRED_CHANNEL:
        return True
    try:
        r = requests.get(
            f"{TELEGRAM_URL}/getChatMember",
            params={"chat_id": REQUIRED_CHANNEL, "user_id": user_id},
            timeout=10
        )
        data = r.json()
        if not data.get("ok"):
            return True  # لو فشل التحقق، نتجاوز
        status = data["result"].get("status", "")
        return status in ("member", "administrator", "creator")
    except Exception:
        return True

def set_required_channel(channel):
    """حفظ القناة الإجبارية"""
    global REQUIRED_CHANNEL
    REQUIRED_CHANNEL = channel
    save_json(CHANNEL_FILE, {"channel": channel})

# ══════════════════════════════════════
#  دوال Groq
# ══════════════════════════════════════
def ask_groq(messages):
    """يحاول كل المفاتيح عند 429 قبل الاستسلام"""
    data = {
        "model"      : "llama-3.1-8b-instant",
        "messages"   : messages,
        "temperature": 0.3,
        "max_tokens" : 2048
    }
    attempts = len(GROQ_API_KEYS)
    for _ in range(attempts):
        headers = {
            "Authorization": f"Bearer {_get_groq_key()}",
            "Content-Type" : "application/json"
        }
        try:
            r = requests.post(GROQ_URL, headers=headers, json=data, timeout=60)
            if r.status_code in (429, 401):
                log.warning(f"Groq key #{_groq_index+1} returned {r.status_code}, switching...")
                _next_groq_key()
                time.sleep(0.5)
                continue
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except requests.exceptions.Timeout:
            return "⏱ انتهت مهلة الاتصال، حاول مرة أخرى"
        except requests.exceptions.HTTPError:
            _next_groq_key()
            continue
        except requests.exceptions.RequestException as e:
            return f"❌ خطأ في الاتصال: {e}"
        except (KeyError, IndexError):
            return "❌ استجابة غير صحيحة من الخادم"
    return "⏳ كل المفاتيح مشغولة حالياً، حاول بعد لحظة"


def ask_groq_vision(messages, image_b64):
    """يحاول كل المفاتيح عند 429 قبل الاستسلام"""
    msgs = copy.deepcopy(messages)
    last_text = msgs[-1]["content"]
    msgs[-1]["content"] = [
        {"type": "text",      "text": last_text},
        {"type": "image_url", "image_url": {"url": image_b64}}
    ]
    data = {
        "model"      : "llama-3.2-90b-vision-preview",
        "messages"   : msgs,
        "temperature": 0.3,
        "max_tokens" : 2048
    }
    attempts = len(GROQ_API_KEYS)
    for _ in range(attempts):
        headers = {
            "Authorization": f"Bearer {_get_groq_key()}",
            "Content-Type" : "application/json"
        }
        try:
            r = requests.post(GROQ_URL, headers=headers, json=data, timeout=90)
            if r.status_code in (429, 401):
                log.warning(f"Groq vision key #{_groq_index+1} returned {r.status_code}, switching...")
                _next_groq_key()
                time.sleep(0.5)
                continue
            if r.status_code == 400:
                return "❌ خطأ في الصورة: تأكد أن الصورة واضحة وصيغتها JPEG/PNG"
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except requests.exceptions.Timeout:
            return "⏱ انتهت مهلة الاتصال عند معالجة الصورة"
        except requests.exceptions.HTTPError:
            _next_groq_key()
            continue
        except Exception as e:
            return f"❌ خطأ في معالجة الصورة: {e}"
    return "⏳ كل المفاتيح مشغولة حالياً، حاول بعد لحظة"


# ══════════════════════════════════════
#  إدارة الجروبات والقنوات
# ══════════════════════════════════════
def register_chat(chat):
    cid = str(chat.get("id", ""))
    if cid and cid not in bot_chats:
        bot_chats[cid] = {
            "title"   : chat.get("title", "—"),
            "type"    : chat.get("type", "—"),
            "added_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        }
        save_json(CHATS_FILE, bot_chats)

def unregister_chat(chat_id):
    cid = str(chat_id)
    if cid in bot_chats:
        del bot_chats[cid]
        save_json(CHATS_FILE, bot_chats)

# ══════════════════════════════════════
#  إدارة ذاكرة المستخدم
# ══════════════════════════════════════
def process_file(content, name):
    try:
        if name.lower().endswith(SUPPORTED_EXT):
            try:
                return content.decode("utf-8")
            except UnicodeDecodeError:
                return content.decode("latin-1", errors="replace")
        return f"ملف: {name}\nالحجم: {len(content):,} بايت\n(نوع غير مدعوم للقراءة النصية)"
    except Exception as e:
        return f"خطأ في قراءة الملف: {e}"


def get_history(chat_id, user_info=None):
    """
    يجلب تاريخ المحادثة.
    user_info: dict من message["from"] — يُستخدم لإشعار الأدمن بالمستخدم الجديد.
    """
    cid    = str(chat_id)
    is_new = cid not in user_memory
    if is_new:
        user_memory[cid] = {
            "history"  : [{"role": "system", "content": SYSTEM_PROMPT}],
            "name"     : "",
            "username" : "",
            "joined_at": datetime.now(timezone.utc).isoformat(),
            "msg_count": 0
        }
        stats["total_users"] += 1
        save_json(STATS_FILE, stats)

        # ── إشعار الأدمن بمستخدم جديد ──
        if user_info:
            name   = user_info.get("first_name", "") or user_info.get("username", "مجهول")
            uname  = user_info.get("username", "")
            uid_v  = user_info.get("id", "")
            uname_display = f"@{uname}" if uname else "بدون يوزر"
            notif = (
    f"🆕 *مستخدم جديد دخل البوت!*\n\n"
    f"👤 الاسم: {name}\n"
    f"🔗 اليوزر: {uname_display}\n"
    f"🆔 الآيدي: `{uid_v}`\n"
    f"👥 عدد المستخدمين: `{stats['total_users']}`"
)
            for admin_id in ADMINS:
                send_message(admin_id, notif)

    return user_memory[cid]["history"]

def trim_history(chat_id):
    cid = str(chat_id)
    h   = user_memory[cid]["history"]
    if len(h) > MAX_HISTORY:
        user_memory[cid]["history"] = [h[0]] + h[-(MAX_HISTORY - 1):]

def push_user(chat_id, content):
    get_history(chat_id).append({"role": "user", "content": content})
    trim_history(chat_id)

def push_assistant(chat_id, content):
    cid = str(chat_id)
    user_memory[cid]["history"].append({"role": "assistant", "content": content})
    user_memory[cid]["msg_count"] = user_memory[cid].get("msg_count", 0) + 1
    stats["total_messages"] += 1
    save_json(STATS_FILE,  stats)
    save_json(MEMORY_FILE, user_memory)

# ══════════════════════════════════════
#  نصوص الأدمن
# ══════════════════════════════════════
def build_stats_text(cid=None):
    started = stats.get("started_at", "—")
    try:
        dt = datetime.fromisoformat(started)
        started = dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        pass
    groups   = sum(1 for v in bot_chats.values() if v.get("type") in ("group","supergroup"))
    channels = sum(1 for v in bot_chats.values() if v.get("type") == "channel")
    ch_line  = f"\n📌 قناة إجبارية      : `{REQUIRED_CHANNEL or 'لا توجد'}`"
    lines = [
        "📊 *إحصائيات البوت الكاملة*\n",
        f"👥 إجمالي المستخدمين : `{stats['total_users']}`",
        f"💬 إجمالي الرسائل    : `{stats['total_messages']}`",
        f"🖼 صور محللة         : `{stats.get('total_images', 0)}`",
        f"📂 ملفات معالجة      : `{stats.get('total_files', 0)}`",
        f"🔧 استخدامات /dew    : `{stats.get('dew_used', 0)}`",
        f"🏘 المجموعات         : `{groups}`",
        f"📣 القنوات           : `{channels}`",
        f"🚫 المحظورون         : `{len(banned_users)}`",
        ch_line,
        f"🕐 تاريخ التشغيل     : `{started}`",
    ]
    if cid:
        uid_data = user_memory.get(str(cid), {})
        lines += [
            "",
            "👤 *بياناتك الشخصية*",
            f"🧠 رسائلك المحفوظة : `{len(uid_data.get('history', [])) - 1}`",
            f"📨 مجموع رسائلك    : `{uid_data.get('msg_count', 0)}`",
            f"📅 انضممت          : `{uid_data.get('joined_at', '—')[:10]}`",
        ]
    return "\n".join(lines)

def build_chats_text():
    if not bot_chats:
        return "🏘 *الجروبات والقنوات*\n\nلا يوجد مجموعات أو قنوات مسجلة."
    lines = ["🏘 *الجروبات والقنوات:*\n"]
    for cid, info in list(bot_chats.items())[-50:]:
        icon  = "📣" if info.get("type") == "channel" else "👥"
        lines.append(f"{icon} `{cid}` — *{info.get('title','—')}* ({info.get('added_at','—')})")
    return "\n".join(lines)

# ══════════════════════════════════════
#  معالجة /dew — يعمل في DM والمجموعات
# ══════════════════════════════════════
def handle_dew(message, chat_id, reply_to_id):
    cid  = str(chat_id)
    text = message.get("text", "")

    parts    = text.split(None, 1)
    question = parts[1].strip() if len(parts) > 1 else ""
    if question.startswith("@"):
        q2       = question.split(None, 1)
        question = q2[1].strip() if len(q2) > 1 else ""

    replied = message.get("reply_to_message", {})
    send_typing(chat_id)
    stats["dew_used"] = stats.get("dew_used", 0) + 1

    # رد على صورة
    if "photo" in replied:
        file_content, err = get_file(replied["photo"][-1]["file_id"])
        if err:
            send_message(chat_id, err, reply_to=reply_to_id)
            return
        caption = question or replied.get("caption") or "حلل هذه الصورة واشرح المشكلة بالتفصيل"
        push_user(cid, caption)
        img_b64 = "data:image/jpeg;base64," + base64.b64encode(file_content).decode()
        reply   = ask_groq_vision(get_history(cid), img_b64)
        push_assistant(cid, reply)
        stats["total_images"] = stats.get("total_images", 0) + 1
        save_json(STATS_FILE, stats)
        send_message(chat_id, reply, reply_to=reply_to_id)
        return

    # رد على ملف — تحليل وإصلاح تلقائي
    if "document" in replied:
        doc       = replied["document"]
        file_name = doc.get("file_name", "unknown")
        file_content, err = get_file(doc["file_id"])
        if err:
            send_message(chat_id, err, reply_to=reply_to_id)
            return
        stats["total_files"] = stats.get("total_files", 0) + 1
        save_json(STATS_FILE, stats)
        handle_file_fix(chat_id, file_content, file_name, reply_to_id)
        return

    # رد على نص
    if "text" in replied and not question:
        question = replied["text"]

    if not question:
        send_message(chat_id,
                     "❓ *كيف تستخدم /dew:*\n\n"
                     "`/dew سؤالك هنا`\n"
                     "أو رد على صورة/ملف/نص بـ /dew",
                     reply_to=reply_to_id)
        return

    push_user(cid, question)
    reply = ask_groq(get_history(cid))
    push_assistant(cid, reply)
    send_message(chat_id, reply, reply_to=reply_to_id)


# ══════════════════════════════════════
#  معالجة الأزرار
# ══════════════════════════════════════
def handle_callback(callback):
    data       = callback["data"]
    cb_id      = callback["id"]
    chat_id    = callback["message"]["chat"]["id"]
    message_id = callback["message"]["message_id"]
    uid        = str(callback["from"]["id"])
    is_admin   = int(uid) in ADMINS

    answer_callback(cb_id)

    if data == "stats_me":

        user_data = user_memory.get(uid, {})

        text = (
            "📊 *إحصائياتك*\n\n"
            f"🧠 الرسائل المحفوظة: `{len(user_data.get('history', [])) - 1}`\n"
            f"📨 عدد رسائلك: `{user_data.get('msg_count', 0)}`\n"
            f"📅 تاريخ الانضمام: `{user_data.get('joined_at', '—')[:10]}`"
        )

        edit_message(
            chat_id,
            message_id,
            text,
            back_button()
        )
        return

    # ── زر التحقق من الاشتراك ──
    if data == "check_subscription":
        if check_subscription(int(uid)):
            edit_message(chat_id, message_id,
                         "✅ *تم التحقق! أهلاً بك.*\n\nالآن يمكنك استخدام البوت.",
                         main_menu())
        else:
            answer_callback(cb_id, "❌ لم تشترك بعد! اشترك ثم اضغط التحقق.", alert=True)
        return

    if data == "noop":
        return

    if data == "main_menu":
        edit_message(chat_id, message_id, "🏠 *القائمة الرئيسية*", main_menu())
        return

    if data == "ask_me":
        edit_message(chat_id, message_id,
                     "💬 *اسألني أي شيء عن Python!*\n\nاكتب سؤالك مباشرة هنا.",
                     back_button())
        return

    # أزرار الأدمن — حماية
    if not is_admin and data.startswith("admin"):
        answer_callback(cb_id, "⛔ غير مصرح لك", alert=True)
        return

    if data == "back_admin":
        edit_message(chat_id, message_id, "🛠 *لوحة الأدمن*", admin_menu())
        return

    if data == "admin_stats":
        edit_message(chat_id, message_id, build_stats_text(), admin_menu())
        return

    if data == "admin_users":
        lines = ["👥 *المستخدمون (آخر 30):*\n"]
        for uid_k, udata in list(user_memory.items())[-30:]:
            name   = udata.get("name", "—") if isinstance(udata, dict) else "—"
            count  = udata.get("msg_count", 0) if isinstance(udata, dict) else 0
            banned = " 🚫" if uid_k in banned_users else ""
            lines.append(f"• `{uid_k}` | {name} | {count} رسالة{banned}")
        edit_message(chat_id, message_id, "\n".join(lines), admin_menu())
        return

    if data == "admin_chats":
        edit_message(chat_id, message_id, build_chats_text(), admin_menu())
        return

    if data == "admin_broadcast_prompt":
        pending_broadcast[uid] = True
        edit_message(chat_id, message_id,
                     "📢 *أرسل الآن نص الرسالة للمستخدمين:*", back_button())
        return

    if data == "admin_group_broadcast_prompt":
        pending_group_broadcast[uid] = True
        edit_message(chat_id, message_id,
                     "📣 *أرسل الآن نص الرسالة لجميع المجموعات:*", back_button())
        return

    # ── إدارة القناة الإجبارية ──
    if data == "admin_channel_menu":
        edit_message(chat_id, message_id,
                     "📌 *إدارة الاشتراك الإجباري*",
                     channel_menu(REQUIRED_CHANNEL))
        return

    if data == "admin_addchannel_prompt":
        pending_addchannel[uid] = True
        edit_message(chat_id, message_id,
                     "📌 *أرسل يوزرنيم القناة:*\n\nمثال: `@mychannel`\n\n"
                     "⚠️ تأكد أن البوت أدمن في القناة أولاً!",
                     back_button())
        return

    if data == "admin_removechannel":
        set_required_channel(None)
        edit_message(chat_id, message_id,
                     "✅ *تم إلغاء الاشتراك الإجباري بنجاح.*",
                     admin_menu())
        return

    if data == "admin_ban_prompt":
        pending_ban[uid] = True
        edit_message(chat_id, message_id,
                     "🚫 *أرسل ID المستخدم الذي تريد حظره:*", back_button())
        return

    if data == "admin_unban_prompt":
        pending_unban[uid] = True
        edit_message(chat_id, message_id,
                     "✅ *أرسل ID المستخدم الذي تريد رفع حظره:*", back_button())
        return

    if data == "admin_clear_prompt":
        pending_clear[uid] = True
        edit_message(chat_id, message_id,
                     "🗑 *أرسل ID المستخدم الذي تريد مسح ذاكرته:*", back_button())
        return


# ══════════════════════════════════════
#  أوامر DM
# ══════════════════════════════════════
def handle_command(chat_id, command, is_admin, user_name="", username="", user_obj=None):
    cid = str(chat_id)

    if command.startswith("/start"):
        get_history(cid, user_obj)
        user_memory[cid]["name"]     = user_name
        user_memory[cid]["username"] = username
        save_json(MEMORY_FILE, user_memory)
        send_message(chat_id,
                     f"🐍 *أهلاً {user_name or 'بك'} في بوت Python!*\n\n"
                     "اسألني أي شيء عن Python مباشرةً،\n"
                     "أو أرسل صورة/ملف للتحليل.\n\n"
                     "في المجموعات استخدم الأمر /dew",
                     reply_markup=main_menu())
        # لوحة الأدمن تلقائياً عند /start
        if is_admin:
            send_message(chat_id, "🛠 *لوحة الأدمن*", reply_markup=admin_menu())
        return True

    if command == "/menu":
        send_message(chat_id, "🏠 *القائمة الرئيسية*", reply_markup=main_menu())
        return True

    if command == "/clear":
        user_memory[cid]["history"] = [{"role": "system", "content": SYSTEM_PROMPT}]
        save_json(MEMORY_FILE, user_memory)
        send_message(chat_id, "✅ تم مسح المحادثة")
        return True

    if command == "/stats":
        send_message(chat_id, build_stats_text(cid))
        return True

    if command == "/help":
        send_message(chat_id,
                     "📚 *طريقة الاستخدام:*\n\n"
                     "*في المحادثة الخاصة:*\n"
                     "• اكتب سؤالك مباشرة\n"
                     "• أرسل صورة فيها كود\n"
                     "• أرسل ملف .py أو .txt\n\n"
                     "*في المجموعات:*\n"
                     "`/dew سؤالك هنا`\n"
                     "رد على صورة/ملف/نص بـ /dew\n\n"
                     "*أوامر:* /menu /clear /stats /help",
                     reply_markup=back_button())
        return True

    if command == "/admin" and is_admin:
        send_message(chat_id, "🛠 *لوحة الأدمن*", reply_markup=admin_menu())
        return True

    return False


def _do_broadcast(admin_id, msg_text):
    if not msg_text:
        send_message(admin_id, "❌ الرسالة فارغة")
        return
    send_message(admin_id, f"⏳ جاري الإرسال لـ {len(user_memory)} مستخدم...")
    def _send(uid):
        try:
            send_message(uid, f"📢 *رسالة من الأدمن:*\n\n{msg_text}")
            time.sleep(0.05)
            return True
        except Exception:
            return False
    with ThreadPoolExecutor(max_workers=10) as ex:
        ok = sum(ex.map(_send, user_memory.keys()))
    send_message(admin_id, f"✅ أُرسل لـ {ok} / {len(user_memory)} مستخدم")


def _do_group_broadcast(admin_id, msg_text):
    if not msg_text:
        send_message(admin_id, "❌ الرسالة فارغة")
        return
    send_message(admin_id, f"⏳ جاري الإرسال لـ {len(bot_chats)} مجموعة/قناة...")
    def _send(cid):
        try:
            send_message(cid, f"📣 *إعلان:*\n\n{msg_text}")
            time.sleep(0.1)
            return True
        except Exception:
            return False
    with ThreadPoolExecutor(max_workers=5) as ex:
        ok = sum(ex.map(_send, bot_chats.keys()))
    send_message(admin_id, f"✅ أُرسل لـ {ok} / {len(bot_chats)} مجموعة/قناة")


# ══════════════════════════════════════
#  الحلقة الرئيسية
# ══════════════════════════════════════
offset = 0
log.info("🚀 البوت يعمل...")
log.info(f"🔑 عدد مفاتيح Groq المحملة: {len(GROQ_API_KEYS)}")
for _i, _k in enumerate(GROQ_API_KEYS):
    log.info(f"   مفتاح #{_i+1}: {_k[:8]}...")

while True:
    try:
        resp    = requests.get(
            f"{TELEGRAM_URL}/getUpdates?timeout=100&offset={offset}",
            timeout=120
        )
        updates = resp.json()

        for update in updates.get("result", []):
            offset = update["update_id"] + 1

            if "callback_query" in update:
                try:
                    handle_callback(update["callback_query"])
                except Exception as e:
                    log.error(f"callback error: {e}", exc_info=True)
                continue

            if "edited_message" in update:
                continue

            if "my_chat_member" in update:
                mcm    = update["my_chat_member"]
                chat   = mcm.get("chat", {})
                status = mcm.get("new_chat_member", {}).get("status", "")
                if status in ("member", "administrator"):
                    register_chat(chat)
                elif status in ("left", "kicked"):
                    unregister_chat(chat.get("id", ""))
                continue

            message = update.get("message", {})
            if not message:
                continue

            chat      = message.get("chat", {})
            chat_id   = str(chat.get("id", ""))
            if not chat_id:
                continue

            chat_type = chat.get("type", "private")
            is_group  = chat_type in ("group", "supergroup")
            user      = message.get("from", {})
            uid       = str(user.get("id", ""))
            user_name = user.get("first_name", "") or user.get("username", "")
            username  = user.get("username", "")
            is_admin  = int(uid) in ADMINS if uid else False
            msg_id    = message.get("message_id")

            if is_group:
                register_chat(chat)

            if uid in banned_users:
                continue

            try:
                if "text" in message:
                    text = message["text"]

                    if text.lstrip().startswith("/dew"):
                        handle_dew(message, chat_id, msg_id)
                        continue

                    if is_group:
                        continue

                    # حالات الأدمن المعلّقة
                    if uid in pending_broadcast and pending_broadcast.pop(uid):
                        _do_broadcast(uid, text)
                        continue
                    if uid in pending_group_broadcast and pending_group_broadcast.pop(uid):
                        _do_group_broadcast(uid, text)
                        continue
                    if uid in pending_addchannel and pending_addchannel.pop(uid):
                        ch = text.strip()
                        if not ch.startswith("@"):
                            ch = "@" + ch
                        set_required_channel(ch)
                        send_message(uid,
                                     f"✅ *تم تفعيل الاشتراك الإجباري!*\n\n"
                                     f"📌 القناة: `{ch}`\n\n"
                                     f"⚠️ تأكد أن البوت أدمن في القناة.",
                                     reply_markup=admin_menu())
                        continue
                    if uid in pending_ban and pending_ban.pop(uid):
                        banned_users.add(text.strip())
                        save_json(BANNED_FILE, list(banned_users))
                        send_message(uid, f"🚫 تم حظر المستخدم `{text.strip()}`")
                        continue
                    if uid in pending_unban and pending_unban.pop(uid):
                        banned_users.discard(text.strip())
                        save_json(BANNED_FILE, list(banned_users))
                        send_message(uid, f"✅ تم رفع الحظر عن `{text.strip()}`")
                        continue
                    if uid in pending_clear and pending_clear.pop(uid):
                        target = text.strip()
                        if target in user_memory:
                            user_memory[target]["history"] = [{"role": "system", "content": SYSTEM_PROMPT}]
                            save_json(MEMORY_FILE, user_memory)
                            send_message(uid, f"🗑 تم مسح ذاكرة `{target}`")
                        else:
                            send_message(uid, f"❓ المستخدم `{target}` غير موجود")
                        continue

                    if handle_command(chat_id, text, is_admin, user_name, username, user):
                        continue

                    # ── تحقق من الاشتراك الإجباري (غير الأدمن فقط) ──
                    if not is_admin and REQUIRED_CHANNEL and not check_subscription(int(uid)):
                        send_message(
                            chat_id,
                            f"⚠️ *يجب الاشتراك في قناتنا أولاً!*\n\n"
                            f"اشترك ثم اضغط ✅ تحققت.",
                            reply_markup=subscription_required_keyboard(REQUIRED_CHANNEL)
                        )
                        continue

                    now  = time.time()
                    last = user_last_message.get(chat_id, 0)
                    if now - last < RATE_LIMIT:
                        send_message(chat_id, f"⏳ انتظر {RATE_LIMIT} ثواني بين الرسائل...")
                        continue
                    user_last_message[chat_id] = now

                    push_user(chat_id, text)
                    send_typing(chat_id)
                    reply = ask_groq(get_history(chat_id, user))
                    push_assistant(chat_id, reply)
                    send_message(chat_id, reply)

                elif "photo" in message and not is_group:
                    # ── تحقق من الاشتراك الإجباري ──
                    if not is_admin and REQUIRED_CHANNEL and not check_subscription(int(uid)):
                        send_message(
                            chat_id,
                            f"⚠️ *يجب الاشتراك في قناتنا أولاً!*\n\n"
                            f"اشترك ثم اضغط ✅ تحققت.",
                            reply_markup=subscription_required_keyboard(REQUIRED_CHANNEL)
                        )
                        continue
                    file_content, err = get_file(message["photo"][-1]["file_id"])
                    if err:
                        send_message(chat_id, err)
                    else:
                        caption = message.get("caption", "حلل هذه الصورة")
                        push_user(chat_id, caption)
                        send_typing(chat_id)
                        img_b64 = "data:image/jpeg;base64," + base64.b64encode(file_content).decode()
                        reply = ask_groq_vision(get_history(chat_id, user), img_b64)
                        push_assistant(chat_id, reply)
                        stats["total_images"] = stats.get("total_images", 0) + 1
                        save_json(STATS_FILE, stats)
                        send_message(chat_id, reply)

                elif "document" in message and not is_group:
                    # ── تحقق من الاشتراك الإجباري ──
                    if not is_admin and REQUIRED_CHANNEL and not check_subscription(int(uid)):
                        send_message(
                            chat_id,
                            f"⚠️ *يجب الاشتراك في قناتنا أولاً!*\n\n"
                            f"اشترك ثم اضغط ✅ تحققت.",
                            reply_markup=subscription_required_keyboard(REQUIRED_CHANNEL)
                        )
                        continue
                    doc       = message["document"]
                    file_name = doc.get("file_name", "unknown")
                    file_content, err = get_file(doc["file_id"])
                    if err:
                        send_message(chat_id, err)
                    else:
                        stats["total_files"] = stats.get("total_files", 0) + 1
                        save_json(STATS_FILE, stats)
                        handle_file_fix(chat_id, file_content, file_name)

            except Exception as e:
                log.error(f"update error: {e}", exc_info=True)
                try:
                    send_message(chat_id, "❌ حدث خطأ، حاول مرة أخرى")
                except Exception:
                    pass

    except Exception as e:
        log.error(f"connection error: {e}")
        time.sleep(5)

