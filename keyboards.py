# keyboards.py

import os
BOT_USERNAME = os.getenv("BOT_USERNAME", "your_bot")

def main_menu():
    return {
        "inline_keyboard": [
            [
                {"text": "➕ أضفني لمجموعاتك", "url": f"https://t.me/{BOT_USERNAME}?startgroup=true"},
                {"text": "💬 اسألني", "callback_data": "ask_me"}
            ]
        ]
    }

def back_button():
    return {
        "inline_keyboard": [
            [{"text": "🔙 رجوع للقائمة", "callback_data": "main_menu"}]
        ]
    }

def admin_menu():
    return {
        "inline_keyboard": [
            [{"text": "📊 إحصائيات كاملة",       "callback_data": "admin_stats"}],
            [{"text": "👥 قائمة المستخدمين",      "callback_data": "admin_users"}],
            [{"text": "🏘 الجروبات والقنوات",      "callback_data": "admin_chats"}],
            [{"text": "📢 بث رسالة للمستخدمين",   "callback_data": "admin_broadcast_prompt"}],
            [{"text": "📣 بث لجميع المجموعات",     "callback_data": "admin_group_broadcast_prompt"}],
            [{"text": "📌 إدارة الاشتراك الإجباري","callback_data": "admin_channel_menu"}],
            [{"text": "🚫 حظر مستخدم",             "callback_data": "admin_ban_prompt"}],
            [{"text": "✅ رفع حظر مستخدم",         "callback_data": "admin_unban_prompt"}],
            [{"text": "🗑 مسح ذاكرة مستخدم",       "callback_data": "admin_clear_prompt"}],
            [{"text": "🔙 رجوع",                   "callback_data": "main_menu"}]
        ]
    }

def channel_menu(current_channel=None):
    ch_text = f"القناة الحالية: {current_channel}" if current_channel else "لا توجد قناة مفعّلة"
    return {
        "inline_keyboard": [
            [{"text": f"📌 {ch_text}", "callback_data": "noop"}],
            [{"text": "➕ إضافة / تغيير القناة",  "callback_data": "admin_addchannel_prompt"}],
            [{"text": "🗑 إلغاء الاشتراك الإجباري","callback_data": "admin_removechannel"}],
            [{"text": "🔙 رجوع للوحة الأدمن",      "callback_data": "back_admin"}]
        ]
    }

def subscription_required_keyboard(channel_username):
    return {
        "inline_keyboard": [
            [{"text": "📢 اشترك في القناة", "url": f"https://t.me/{channel_username.lstrip('@')}"}],
            [{"text": "✅ تحققت من الاشتراك", "callback_data": "check_subscription"}]
        ]
    }
