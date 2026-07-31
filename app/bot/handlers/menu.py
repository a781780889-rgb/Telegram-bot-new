from aiogram import Router, F, types
from app.bot.keyboards.main_menu import get_main_menu, get_back_button
from app.database.database import AsyncSessionLocal
from app.database.repositories.user_repo import UserRepository
from app.config.config import settings

router = Router()

# Sections that have dedicated handlers in other routers.
# They must NOT be caught by the generic handler below.
_DEDICATED = frozenset({"search"})

SECTION_TITLES = {
    "links":       "🔗 الروابط",
    "folders":     "📁 المجلدات",
    "publishing":  "🚀 محرك النشر",
    "stats":       "📊 الإحصائيات",
    "subs":        "💎 الاشتراكات",
    "settings":    "⚙️ الإعدادات",
    "help":        "❓ المساعدة",
}


@router.callback_query(F.data.startswith("menu:"))
async def generic_menu_handler(callback: types.CallbackQuery):
    section_key = callback.data.split(":", 1)[1]

    # Dedicated handlers are registered in their own routers which are
    # included BEFORE this router, so they will already have handled the
    # callback. This guard is a safety net in case order is ever changed.
    if section_key in _DEDICATED:
        await callback.answer()
        return

    title = SECTION_TITLES.get(section_key, "هذا القسم")
    await callback.message.edit_text(
        f"{title}\n\n🛠️ هذه الميزة قيد التطوير حالياً وسيتم تفعيلها قريباً.",
        reply_markup=get_back_button("main"),
    )
    await callback.answer()


@router.callback_query(F.data == "back:main")
async def back_to_main(callback: types.CallbackQuery):
    async with AsyncSessionLocal() as db:
        repo = UserRepository(db)
        user = await repo.get_by_id(callback.from_user.id)
        is_admin = (
            user.role.value in ["owner", "admin"]
            if user
            else callback.from_user.id in settings.ADMIN_IDS
        )

    await callback.message.edit_text(
        "🏠 لوحة التحكم الرئيسية\n\nأهلاً بك في بوت إدارة التليجرام الاحترافي.",
        reply_markup=get_main_menu(is_admin=is_admin),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:main")
async def admin_panel(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🛠 لوحة الإدارة\n\n🛠️ هذه الميزة قيد التطوير حالياً وسيتم تفعيلها قريباً.",
        reply_markup=get_back_button("main"),
    )
    await callback.answer()
