"""
SearchEngine — orchestrates one search job.

Lifecycle
─────────
  PENDING → RUNNING → COMPLETED | FAILED | CANCELLED

The engine runs as a background asyncio.Task.  The handler stores
the engine reference in a module-level registry so pause/resume/stop
commands can reach it via the job_id.

Key guarantees
──────────────
• Links are persisted incrementally (not only at the end).
• Stopping the engine does NOT lose links already saved.
• A Pause/Resume cycle does not restart the search from scratch.
• FloodWait and network errors are caught per-link — one bad URL
  never halts the entire job.
• Progress counters are written to the DB periodically, not just at end.
"""

from __future__ import annotations

import asyncio
import io
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from loguru import logger

from app.database.database import AsyncSessionLocal
from app.database.models.search_models import (
    LinkPlatform,
    LinkStatus,
    SearchPlatform,
    SearchStatus,
)
from app.database.repositories.link_repo import LinkRepository
from app.database.repositories.search_repo import SearchJobRepository
from app.services.search.normalizer import NormalizedLink, normalize


# ── module-level registry ──────────────────────────────────────────────────
# Maps job_id → SearchEngine instance so handlers can call pause/stop.

_engines: Dict[int, "SearchEngine"] = {}


def get_engine(job_id: int) -> Optional["SearchEngine"]:
    return _engines.get(job_id)


def register_engine(job_id: int, engine: "SearchEngine") -> None:
    _engines[job_id] = engine


def unregister_engine(job_id: int) -> None:
    _engines.pop(job_id, None)


# ── constants ─────────────────────────────────────────────────────────────

_PROGRESS_INTERVAL = 6   # seconds between bot-message edits
_DB_FLUSH_EVERY    = 20  # links between counter flushes to DB


# ── engine ────────────────────────────────────────────────────────────────

class SearchEngine:
    """
    One instance per search job.  Created by the handler, then
    run as an asyncio background task.
    """

    def __init__(self, job_id: int, bot: Bot, user_id: int) -> None:
        self.job_id  = job_id
        self.bot     = bot
        self.user_id = user_id

        self._stop_event:  asyncio.Event = asyncio.Event()
        self._pause_event: asyncio.Event = asyncio.Event()
        self._pause_event.set()   # starts unpaused

        # Local counters — flushed to DB every _DB_FLUSH_EVERY links
        self._cnt_total: int = 0
        self._cnt_new:   int = 0
        self._cnt_dup:   int = 0
        self._cnt_inv:   int = 0
        self._cnt_tg:    int = 0
        self._cnt_wa:    int = 0
        self._since_flush: int = 0

        self._start_ts: float = 0.0

    # ── public controls ──────────────────────────────────────────────────

    def stop(self)   -> None: self._stop_event.set()
    def pause(self)  -> None: self._pause_event.clear()
    def resume(self) -> None: self._pause_event.set()

    @property
    def is_stopped(self) -> bool: return self._stop_event.is_set()

    # ── main entry point ─────────────────────────────────────────────────

    async def run(self) -> None:
        self._start_ts = time.monotonic()
        register_engine(self.job_id, self)

        async with AsyncSessionLocal() as db:
            repo = SearchJobRepository(db)
            await repo.set_running(self.job_id)
            job  = await repo.get_by_id(self.job_id)
            if job is None:
                unregister_engine(self.job_id)
                return

        try:
            await self._run_search()
            if not self._stop_event.is_set():
                await self._finalize(SearchStatus.COMPLETED)
            else:
                await self._finalize(SearchStatus.CANCELLED)
        except Exception as exc:
            logger.exception(f"SearchEngine job={self.job_id} crashed: {exc}")
            await self._finalize(SearchStatus.FAILED, error=str(exc))
        finally:
            await self._flush_counters()
            unregister_engine(self.job_id)
            await self._send_completion_message()

    # ── search orchestration ─────────────────────────────────────────────

    async def _run_search(self) -> None:
        async with AsyncSessionLocal() as db:
            repo = SearchJobRepository(db)
            job  = await repo.get_by_id(self.job_id)
            if job is None:
                return

        platform          = job.platform.value
        depth             = job.depth.value
        account_ids       = job.account_ids or []
        link_types_config = job.link_types_config or {}
        max_results       = job.max_results

        # Start the progress-updater coroutine
        updater_task = asyncio.create_task(self._progress_updater(job))

        try:
            if platform in ("telegram", "both"):
                await self._run_telegram(account_ids, depth, link_types_config, max_results)

            if not self._stop_event.is_set() and platform in ("whatsapp", "both"):
                await self._run_whatsapp(depth, link_types_config, max_results)

        finally:
            updater_task.cancel()
            try:
                await updater_task
            except asyncio.CancelledError:
                pass

    async def _run_telegram(
        self,
        account_ids: list,
        depth: str,
        link_types_config: dict,
        max_results: int,
    ) -> None:
        from app.services.search.parsers.telegram_parser import search_via_session
        from app.database.models.user import Account

        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            result = await db.execute(
                select(Account).where(Account.id.in_(account_ids))
            )
            accounts = list(result.scalars().all())

        if not accounts:
            logger.warning(f"job={self.job_id} no accounts found for ids={account_ids}")
            return

        for account in accounts:
            if self._stop_event.is_set():
                break

            session_name = account.session_name
            logger.info(f"job={self.job_id} TG search via session={session_name}")

            async for link in search_via_session(
                session_name,
                depth=depth,
                link_types_config=link_types_config,
                stop_event=self._stop_event,
                pause_event=self._pause_event,
            ):
                if self._stop_event.is_set():
                    break
                if self._cnt_total >= max_results:
                    self._stop_event.set()
                    break
                await self._process_link(link, source="telegram_search", account_id=account.id)

    async def _run_whatsapp(
        self,
        depth: str,
        link_types_config: dict,
        max_results: int,
    ) -> None:
        from app.services.search.parsers.whatsapp_parser import search_whatsapp_links

        logger.info(f"job={self.job_id} WhatsApp search, depth={depth}")

        async for link in search_whatsapp_links(
            depth=depth,
            link_types_config=link_types_config,
            stop_event=self._stop_event,
            pause_event=self._pause_event,
        ):
            if self._stop_event.is_set():
                break
            if self._cnt_total >= max_results:
                self._stop_event.set()
                break
            await self._process_link(link, source="web_scrape", account_id=None)

    # ── per-link processing ──────────────────────────────────────────────

    async def _process_link(
        self,
        link: NormalizedLink,
        source: str,
        account_id: Optional[int],
    ) -> None:
        self._cnt_total += 1
        platform = LinkPlatform(link.platform)

        async with AsyncSessionLocal() as db:
            link_repo = LinkRepository(db)
            try:
                is_new, _ = await link_repo.upsert_link(
                    platform=platform,
                    link_type=link.link_type,  # type: ignore[arg-type]
                    original_url=link.original_url,
                    normalized_url=link.normalized_url,
                    url_hash=link.url_hash,
                    search_id=self.job_id,
                    source_account_id=account_id,
                    source=source,
                    username=link.username,
                )
            except Exception as exc:
                logger.error(f"job={self.job_id} link upsert error: {exc}")
                self._cnt_inv += 1
                return

        if is_new:
            self._cnt_new += 1
        else:
            self._cnt_dup += 1

        if link.platform == "telegram":
            self._cnt_tg += 1
        else:
            self._cnt_wa += 1

        self._since_flush += 1
        if self._since_flush >= _DB_FLUSH_EVERY:
            await self._flush_counters()
            self._since_flush = 0

    # ── counters / progress ──────────────────────────────────────────────

    async def _flush_counters(self) -> None:
        async with AsyncSessionLocal() as db:
            repo = SearchJobRepository(db)
            await repo.increment_counters(
                self.job_id,
                total=self._cnt_total,
                new=self._cnt_new,
                duplicate=self._cnt_dup,
                invalid=self._cnt_inv,
                telegram=self._cnt_tg,
                whatsapp=self._cnt_wa,
            )
        # Reset locals after flush to avoid double-counting
        self._cnt_total = self._cnt_new = self._cnt_dup = 0
        self._cnt_inv   = self._cnt_tg  = self._cnt_wa  = 0

    async def _progress_updater(self, job) -> None:
        """Coroutine that edits the bot message every _PROGRESS_INTERVAL seconds."""
        chat_id    = job.chat_id
        message_id = job.message_id
        if not chat_id or not message_id:
            return

        while True:
            await asyncio.sleep(_PROGRESS_INTERVAL)

            async with AsyncSessionLocal() as db:
                repo  = SearchJobRepository(db)
                fresh = await repo.get_by_id(self.job_id)
                if fresh is None:
                    break

            elapsed = int(time.monotonic() - self._start_ts)
            text    = _build_progress_message(fresh, elapsed)

            try:
                await self.bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id, text=text,
                    reply_markup=_running_keyboard(self.job_id),
                )
            except TelegramBadRequest:
                pass  # message not modified — counters unchanged
            except Exception as exc:
                logger.debug(f"progress_updater edit error: {exc}")

    # ── completion ────────────────────────────────────────────────────────

    async def _finalize(self, status: SearchStatus, error: str = "") -> None:
        async with AsyncSessionLocal() as db:
            repo = SearchJobRepository(db)
            if status == SearchStatus.COMPLETED:
                await repo.set_completed(self.job_id)
            elif status == SearchStatus.CANCELLED:
                await repo.set_cancelled(self.job_id)
            else:
                await repo.set_failed(self.job_id, error or "Unknown error")

    async def _send_completion_message(self) -> None:
        async with AsyncSessionLocal() as db:
            repo = SearchJobRepository(db)
            job  = await repo.get_by_id(self.job_id)

        if job is None or not job.chat_id or not job.message_id:
            return

        elapsed = int(time.monotonic() - self._start_ts)
        text    = _build_completion_message(job, elapsed)

        from app.bot.keyboards.search_keyboards import results_keyboard
        try:
            await self.bot.edit_message_text(
                chat_id=job.chat_id,
                message_id=job.message_id,
                text=text,
                reply_markup=results_keyboard(job.id),
            )
        except Exception as exc:
            logger.warning(f"send_completion_message error: {exc}")


# ── message builders ──────────────────────────────────────────────────────

def _build_progress_message(job, elapsed_secs: int) -> str:
    status_emoji = "🔴" if job.status.value == "running" else "⏸️"
    h, m, s = elapsed_secs // 3600, (elapsed_secs % 3600) // 60, elapsed_secs % 60
    time_str = f"{h:02d}:{m:02d}:{s:02d}"

    lines = [
        f"{status_emoji} البحث يعمل الآن — #{job.id}",
        "",
        f"⏱️ الوقت المنقضي: {time_str}",
        f"📊 إجمالي الروابط: {job.found_total:,}",
        f"✅ جديدة:        {job.found_new:,}",
        f"♻️ مكررة:        {job.found_duplicate:,}",
        f"❌ غير صالحة:   {job.found_invalid:,}",
        "",
        f"📱 Telegram:  {job.found_telegram:,}",
        f"💬 WhatsApp:  {job.found_whatsapp:,}",
    ]
    return "\n".join(lines)


def _build_completion_message(job, elapsed_secs: int) -> str:
    status_map = {
        "completed": "✅ اكتمل البحث",
        "cancelled": "⏹️ تم إيقاف البحث",
        "failed":    "❌ فشل البحث",
    }
    title = status_map.get(job.status.value, "✅ انتهى البحث")
    h, m, s = elapsed_secs // 3600, (elapsed_secs % 3600) // 60, elapsed_secs % 60

    lines = [
        f"{title}  —  #{job.id}",
        "",
        f"⏱️ المدة: {h:02d}:{m:02d}:{s:02d}",
        "",
        f"📊 إجمالي الروابط المكتشفة: {job.found_total:,}",
        f"   ├─ ✅ جديدة:     {job.found_new:,}",
        f"   ├─ ♻️ مكررة:     {job.found_duplicate:,}",
        f"   └─ ❌ غير صالحة: {job.found_invalid:,}",
        "",
        f"📱 Telegram:  {job.found_telegram:,}",
        f"💬 WhatsApp:  {job.found_whatsapp:,}",
    ]
    return "\n".join(lines)


def _running_keyboard(job_id: int):
    from app.bot.keyboards.search_keyboards import running_keyboard
    return running_keyboard(job_id)
