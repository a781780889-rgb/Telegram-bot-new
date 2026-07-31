import asyncio

from aiogram import Bot, Dispatcher
from loguru import logger
from sqlalchemy import text

from app.bot.handlers import accounts, menu, start
from app.bot.handlers import search as search_handler
from app.config.config import settings
from app.database.database import Base, engine
from app.services.search.search_job_manager import search_job_manager


async def init_db() -> None:
    """
    Safe DB init:
    1. Drop search-related tables/types that may be stale from old schema.
    2. Create all tables fresh (checkfirst=True skips existing ones).
    """
    async with engine.begin() as conn:
        # Drop stale tables/constraints from old schema versions
        await conn.execute(text("""
            DROP TABLE IF EXISTS duplicate_links   CASCADE;
            DROP TABLE IF EXISTS duplicate_records CASCADE;
            DROP TABLE IF EXISTS discovered_links  CASCADE;
            DROP TABLE IF EXISTS links             CASCADE;
            DROP TABLE IF EXISTS search_jobs       CASCADE;
        """))

        # Drop stale enum types (PostgreSQL keeps them after table drops)
        for typ in [
            "linkplatform", "linktype", "linkstatus",
            "searchstatus", "searchdepth", "searchplatform", "searchperiod",
        ]:
            await conn.execute(text(f"DROP TYPE IF EXISTS {typ} CASCADE;"))

    # Now create everything cleanly
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Database initialized.")


async def main() -> None:
    await init_db()

    bot = Bot(token=settings.BOT_TOKEN)
    dp  = Dispatcher()

    search_job_manager.set_bot(bot)

    dp.include_router(start.router)
    dp.include_router(accounts.router)
    dp.include_router(search_handler.router)
    dp.include_router(menu.router)

    logger.info("Starting bot…")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
