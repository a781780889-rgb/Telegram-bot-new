from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_main_menu(is_admin: bool = False):
    buttons = [
        [InlineKeyboardButton(text="📂 الحسابات", callback_data="menu:accounts"),
         InlineKeyboardButton(text="🔗 الروابط", callback_data="menu:links")],
        [InlineKeyboardButton(text="🔍 البحث", callback_data="menu:search"),
         InlineKeyboardButton(text="📁 المجلدات", callback_data="menu:folders")],
        [InlineKeyboardButton(text="🚀 محرك النشر", callback_data="menu:publishing"),
         InlineKeyboardButton(text="📊 الإحصائيات", callback_data="menu:stats")],
        [InlineKeyboardButton(text="💎 الاشتراكات", callback_data="menu:subs"),
         InlineKeyboardButton(text="⚙️ الإعدادات", callback_data="menu:settings")],
        [InlineKeyboardButton(text="❓ المساعدة", callback_data="menu:help")]
    ]
    
    if is_admin:
        buttons.append([InlineKeyboardButton(text="🛠 لوحة الإدارة", callback_data="admin:main")])
        
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_back_button(target: str = "main"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ رجوع", callback_data=f"back:{target}")]
    ])
