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
    async with engine.begin() as conn:
        # Drop each table/type separately (asyncpg rejects multi-statement strings)
        for stmt in [
            "DROP TABLE IF EXISTS duplicate_links   CASCADE",
            "DROP TABLE IF EXISTS duplicate_records CASCADE",
            "DROP TABLE IF EXISTS discovered_links  CASCADE",
            "DROP TABLE IF EXISTS links             CASCADE",
            "DROP TABLE IF EXISTS search_jobs       CASCADE",
            "DROP TYPE  IF EXISTS linkplatform      CASCADE",
            "DROP TYPE  IF EXISTS linktype          CASCADE",
            "DROP TYPE  IF EXISTS linkstatus        CASCADE",
            "DROP TYPE  IF EXISTS searchstatus      CASCADE",
            "DROP TYPE  IF EXISTS searchdepth       CASCADE",
            "DROP TYPE  IF EXISTS searchplatform    CASCADE",
            "DROP TYPE  IF EXISTS searchperiod      CASCADE",
        ]:
            await conn.execute(text(stmt))

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
