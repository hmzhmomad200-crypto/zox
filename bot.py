import requests
import os
import json
import time
import base64
import copy
import logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from keyboards import main_menu, back_button, admin_menu

# ══════════════════════════════════════
#  إعداد السجلات
# ══════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ══════════════════════════════════════
#  متغيرات البيئة
# ══════════════════════════════════════
BOT_TOKEN    = os.getenv("BOT_TOKEN",    "ضع_توكن_البوت_هنا")
BOT_USERNAME = os.getenv("BOT_USERNAME", "your_bot")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "ضع_مفتاح_GROQ_هنا")
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
MEMORY_FILE   = "user_memory.json"
STATS_FILE    = "stats.json"
CHATS_FILE    = "bot_chats.json"
BANNED_FILE   = "banned_users.json"
SUPPORTED_EXT = ('.txt', '.py', '.js', '.json', '.html',
                 '.css', '.md', '.xml', '.csv')

# حالات معلّقة
pending_broadcast       = {}
pending_group_broadcast = {}
pending_ban             = {}
pending_unban           = {}
pending_clear           = {}

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
#  دوال Groq
# ══════════════════════════════════════
def ask_groq(messages):
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type" : "application/json"
    }
    data = {
        "model"      : "llama-3.3-70b-versatile",
        "messages"   : messages,
        "temperature": 0.3,
        "max_tokens" : 2048
    }
    try:
        r = requests.post(GROQ_URL, headers=headers, json=data, timeout=60)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except requests.exceptions.Timeout:
        return "⏱ انتهت مهلة الاتصال، حاول مرة أخرى"
    except requests.exceptions.HTTPError:
        if r.status_code == 429:
            return "⏳ الخادم مشغول حالياً، حاول بعد لحظة"
        return f"❌ خطأ HTTP {r.status_code}"
    except requests.exceptions.RequestException as e:
        return f"❌ خطأ في الاتصال: {e}"
    except (KeyError, IndexError):
        return "❌ استجابة غير صحيحة من الخادم"


def ask_groq_vision(messages, image_b64):
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type" : "application/json"
    }
    msgs = copy.deepcopy(messages)
    last_text = msgs[-1]["content"]
    msgs[-1]["content"] = [
        {"type": "text",      "text": last_text},
        {"type": "image_url", "image_url": {"url": image_b64}}
    ]
    data = {
        "model"      : "meta-llama/llama-4-scout-17b-16e-instruct",
        "messages"   : msgs,
        "temperature": 0.3,
        "max_tokens" : 2048
    }
    try:
        r = requests.post(GROQ_URL, headers=headers, json=data, timeout=90)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except requests.exceptions.Timeout:
        return "⏱ انتهت مهلة الاتصال عند معالجة الصورة"
    except requests.exceptions.HTTPError:
        if r.status_code == 400:
            return "❌ خطأ في الصورة: تأكد أن الصورة واضحة وصيغتها JPEG/PNG"
        if r.status_code == 429:
            return "⏳ الخادم مشغول، حاول بعد لحظة"
        return f"❌ خطأ HTTP {r.status_code}"
    except Exception as e:
        return f"❌ خطأ في معالجة الصورة: {e}"


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


def get_history(chat_id):
    cid = str(chat_id)
    if cid not in user_memory:
        user_memory[cid] = {
            "history"  : [{"role": "system", "content": SYSTEM_PROMPT}],
            "name"     : "",
            "username" : "",
            "joined_at": datetime.now(timezone.utc).isoformat(),
            "msg_count": 0
        }
        stats["total_users"] += 1
        save_json(STATS_FILE, stats)
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

    # رد على ملف
    if "document" in replied:
        doc       = replied["document"]
        file_name = doc.get("file_name", "unknown")
        file_content, err = get_file(doc["file_id"])
        if err:
            send_message(chat_id, err, reply_to=reply_to_id)
            return
        file_text = process_file(file_content, file_name)
        user_msg  = f"ملف: {file_name}\n\n{file_text[:3000]}"
        if question:
            user_msg += f"\n\nالسؤال: {question}"
        push_user(cid, user_msg)
        reply = ask_groq(get_history(cid))
        push_assistant(cid, reply)
        stats["total_files"] = stats.get("total_files", 0) + 1
        save_json(STATS_FILE, stats)
        send_message(chat_id, reply, reply_to=reply_to_id)
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

    if data == "main_menu":
        edit_message(chat_id, message_id, "🏠 *القائمة الرئيسية*", main_menu())
        return

    if data == "ask_me":
        edit_message(chat_id, message_id,
                     "💬 *اسألني أي شيء عن Python!*\n\nاكتب سؤالك مباشرة هنا.",
                     back_button())
        return

    # أزرار الأدمن
    if not is_admin and data.startswith("admin"):
        answer_callback(cb_id, "⛔ غير مصرح لك", alert=True)
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
def handle_command(chat_id, command, is_admin, user_name="", username=""):
    cid = str(chat_id)

    if command.startswith("/start"):
        get_history(cid)
        user_memory[cid]["name"]     = user_name
        user_memory[cid]["username"] = username
        save_json(MEMORY_FILE, user_memory)
        send_message(chat_id,
                     f"🐍 *أهلاً {user_name or 'بك'} في بوت Python!*\n\n"
                     "اسألني أي شيء عن Python مباشرةً،\n"
                     "أو أرسل صورة/ملف للتحليل.\n\n"
                     "في المجموعات استخدم الأمر /dew",
                     reply_markup=main_menu())
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

                    if handle_command(chat_id, text, is_admin, user_name, username):
                        continue

                    now  = time.time()
                    last = user_last_message.get(chat_id, 0)
                    if now - last < RATE_LIMIT:
                        send_message(chat_id, f"⏳ انتظر {RATE_LIMIT} ثواني بين الرسائل...")
                        continue
                    user_last_message[chat_id] = now

                    push_user(chat_id, text)
                    send_typing(chat_id)
                    reply = ask_groq(get_history(chat_id))
                    push_assistant(chat_id, reply)
                    send_message(chat_id, reply)

                elif "photo" in message and not is_group:
                    file_content, err = get_file(message["photo"][-1]["file_id"])
                    if err:
                        send_message(chat_id, err)
                    else:
                        caption = message.get("caption", "حلل هذه الصورة")
                        push_user(chat_id, caption)
                        send_typing(chat_id)
                        img_b64 = "data:image/jpeg;base64," + base64.b64encode(file_content).decode()
                        reply = ask_groq_vision(get_history(chat_id), img_b64)
                        push_assistant(chat_id, reply)
                        stats["total_images"] = stats.get("total_images", 0) + 1
                        save_json(STATS_FILE, stats)
                        send_message(chat_id, reply)

                elif "document" in message and not is_group:
                    doc       = message["document"]
                    file_name = doc.get("file_name", "unknown")
                    file_content, err = get_file(doc["file_id"])
                    if err:
                        send_message(chat_id, err)
                    else:
                        send_typing(chat_id)
                        file_text = process_file(file_content, file_name)
                        push_user(chat_id, f"ملف: {file_name}\n\n{file_text[:3000]}")
                        reply = ask_groq(get_history(chat_id))
                        push_assistant(chat_id, reply)
                        stats["total_files"] = stats.get("total_files", 0) + 1
                        save_json(STATS_FILE, stats)
                        send_message(chat_id, reply)

            except Exception as e:
                log.error(f"update error: {e}", exc_info=True)
                try:
                    send_message(chat_id, "❌ حدث خطأ، حاول مرة أخرى")
                except Exception:
                    pass

    except Exception as e:
        log.error(f"connection error: {e}")
        time.sleep(5)
