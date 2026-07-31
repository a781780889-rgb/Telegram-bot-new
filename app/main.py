import asyncio
import logging

from aiogram import Bot, Dispatcher
from loguru import logger

from app.bot.handlers import accounts, menu, start
from app.bot.handlers import search as search_handler
from app.config.config import settings
from app.database.database import Base, engine
from app.services.search.search_job_manager import search_job_manager


async def init_db() -> None:
    """Create all tables.  For production use Alembic migrations instead."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def main() -> None:
    # ── database ──────────────────────────────────────────────────────
    await init_db()

    # ── bot + dispatcher ──────────────────────────────────────────────
    bot = Bot(token=settings.BOT_TOKEN)
    dp  = Dispatcher()

    # Wire the job manager so it can edit progress messages via the bot
    search_job_manager.set_bot(bot)

    # ── routers  (order matters: more-specific first) ─────────────────
    dp.include_router(start.router)
    dp.include_router(accounts.router)
    dp.include_router(search_handler.router)   # handles menu:search + srch:*
    dp.include_router(menu.router)             # generic fallback for other menu:* keys

    logger.info("Starting bot…")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
