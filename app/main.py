import asyncio
import logging
from aiogram import Bot, Dispatcher
from app.config.config import settings
from app.bot.handlers import start, accounts, menu
from app.bot.handlers import search  # ← NEW
from app.database.database import engine, Base

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def init_db():
    async with engine.begin() as conn:
        # Creates all tables (including new search tables).
        # For production use Alembic migrations instead.
        await conn.run_sync(Base.metadata.create_all)


async def main():
    await init_db()

    bot = Bot(token=settings.BOT_TOKEN)
    dp  = Dispatcher()

    # ── router order matters ──────────────────────────────────────────────
    # search.router must come BEFORE menu.router so that
    # F.data == "menu:search" is caught by the search handler
    # rather than the generic "menu:*" handler in menu.py.
    dp.include_router(start.router)
    dp.include_router(accounts.router)
    dp.include_router(search.router)   # ← NEW (before menu)
    dp.include_router(menu.router)

    logger.info("Starting bot...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped!")
