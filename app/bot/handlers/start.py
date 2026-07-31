from aiogram import Router, types
from aiogram.filters import CommandStart
from app.bot.keyboards.main_menu import get_main_menu
from app.database.database import AsyncSessionLocal
from app.database.repositories.user_repo import UserRepository
from app.config.config import settings

router = Router()

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    async with AsyncSessionLocal() as db:
        repo = UserRepository(db)
        user = await repo.get_by_id(message.from_user.id)
        if not user:
            is_admin = message.from_user.id in settings.ADMIN_IDS
            from app.database.models.user import UserRole
            role = UserRole.ADMIN if is_admin else UserRole.USER
            await repo.create(
                user_id=message.from_user.id,
                username=message.from_user.username,
                full_name=message.from_user.full_name,
                role=role
            )
        
        is_admin = user.role.value in ["owner", "admin"] if user else message.from_user.id in settings.ADMIN_IDS
        
        await message.answer(
            "🏠 لوحة التحكم الرئيسية\n\nأهلاً بك في بوت إدارة التليجرام الاحترافي.",
            reply_markup=get_main_menu(is_admin=is_admin)
        )
