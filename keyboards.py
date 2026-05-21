import os

BOT_USERNAME = os.getenv("BOT_USERNAME", "your_bot")

ASK_ME_TEXT = "💬 اسألني"
STATS_ME_TEXT = "📊 إحصائياتي"
ADD_TO_GROUP_TEXT = "➕ أضفني للمجموعة"
ADD_TO_GROUP_URL = f"https://t.me/{BOT_USERNAME}?startgroup=invite"

ADMIN_STATS_TEXT = "📊 إحصائيات كاملة"
ADMIN_USERS_TEXT = "👥 قائمة المستخدمين"
ADMIN_CHATS_TEXT = "🏘 الجروبات والقنوات"
ADMIN_BROADCAST_PROMPT_TEXT = "📢 بث رسالة للمستخدمين"
ADMIN_GROUP_BROADCAST_PROMPT_TEXT = "📣 بث لجميع المجموعات"
ADMIN_CHANNEL_MENU_TEXT = "📌 إدارة الاشتراك الإجباري"
ADMIN_BAN_PROMPT_TEXT = "🚫 حظر مستخدم"
ADMIN_UNBAN_PROMPT_TEXT = "✅ رفع حظر مستخدم"
ADMIN_CLEAR_PROMPT_TEXT = "🗑 مسح ذاكرة مستخدم"

KEYBOARDS = {
    "main_menu": [
        {"text": ASK_ME_TEXT, "callback_data": "ask_me"},
        {"text": STATS_ME_TEXT, "callback_data": "stats_me"},
        {"text": ADD_TO_GROUP_TEXT, "url": ADD_TO_GROUP_URL},
    ],
    "back_button": [
        {"text": "🔙 رجوع للقائمة", "callback_data": "main_menu"}
    ],
    "admin_menu": [
        {"text": ADMIN_STATS_TEXT, "callback_data": "admin_stats"},
        {"text": ADMIN_USERS_TEXT, "callback_data": "admin_users"},
        {"text": ADMIN_CHATS_TEXT, "callback_data": "admin_chats"},
        {"text": ADMIN_BROADCAST_PROMPT_TEXT, "callback_data": "admin_broadcast_prompt"},
        {"text": ADMIN_GROUP_BROADCAST_PROMPT_TEXT, "callback_data": "admin_group_broadcast_prompt"},
        {"text": ADMIN_CHANNEL_MENU_TEXT, "callback_data": "admin_channel_menu"},
        {"text": ADMIN_BAN_PROMPT_TEXT, "callback_data": "admin_ban_prompt"},
        {"text": ADMIN_UNBAN_PROMPT_TEXT, "callback_data": "admin_unban_prompt"},
        {"text": ADMIN_CLEAR_PROMPT_TEXT, "callback_data": "admin_clear_prompt"},
        {"text": "🔙 رجوع", "callback_data": "main_menu"}
    ]
}

def create_button(text, callback_data=None, url=None):
    button = {"text": text}
    if callback_data:
        button["callback_data"] = callback_data
    if url:
        button["url"] = url
    return [button]

def create_keyboard(keyboard_name):
    return {"inline_keyboard": [KEYBOARDS[keyboard_name]]}

def main_menu():
    return create_keyboard("main_menu")

def back_button():
    return create_keyboard("back_button")

def admin_menu():
    return create_keyboard("admin_menu")

def channel_menu(current_channel=None):
    ch_text = f"القناة الحالية: {current_channel}" if current_channel else "لا توجد قناة مفعّلة"
    return {
        "inline_keyboard": [
            create_button(f"📌 {ch_text}", callback_data="noop"),
            create_button("➕ إضافة / تغيير القناة", callback_data="admin_addchannel_prompt"),
            create_button("🗑 إلغاء الاشتراك الإجباري", callback_data="admin_removechannel"),
            create_button("🔙 رجوع للوحة الأدمن", callback_data="back_admin")
        ]
    }

def subscription_required_keyboard(channel_username):
    return {
        "inline_keyboard": [
            create_button("📢 اشترك في القناة", url=f"https://t.me/{channel_username.lstrip('@')}"),
            create_button("✅ تحققت من الاشتراك", callback_data="check_subscription")
        ]
    }
