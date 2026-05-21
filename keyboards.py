# keyboards.py

def main_menu():
    return {
        "inline_keyboard": [
            [
                {"text": "➕ أضفني لمجموعاتك", "url": "https://t.me/BOT_USERNAME?startgroup=true"},
                {"text": "💬 اسألني",          "callback_data": "ask_me"}
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
            [{"text": "📊 إحصائيات كاملة",         "callback_data": "admin_stats"}],
            [{"text": "👥 قائمة المستخدمين",        "callback_data": "admin_users"}],
            [{"text": "🏘 الجروبات والقنوات",        "callback_data": "admin_chats"}],
            [{"text": "📢 بث رسالة للمستخدمين",     "callback_data": "admin_broadcast_prompt"}],
            [{"text": "📣 بث لجميع المجموعات",      "callback_data": "admin_group_broadcast_prompt"}],
            [{"text": "🚫 حظر مستخدم",              "callback_data": "admin_ban_prompt"}],
            [{"text": "✅ رفع حظر مستخدم",          "callback_data": "admin_unban_prompt"}],
            [{"text": "🗑 مسح ذاكرة مستخدم",        "callback_data": "admin_clear_prompt"}],
            [{"text": "🔙 رجوع",                    "callback_data": "main_menu"}]
        ]
    }
