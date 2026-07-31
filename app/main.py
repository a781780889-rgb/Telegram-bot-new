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
        # Create all tables (safe — skips existing)
        await conn.run_sync(Base.metadata.create_all)

        # Safe migrations — add columns if missing
        safe_alters = [
            "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS session_string TEXT",
            "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS is_connected BOOLEAN DEFAULT FALSE",
            "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'active'",
            "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS last_check TIMESTAMP WITH TIME ZONE",
        ]
        for stmt in safe_alters:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass

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
