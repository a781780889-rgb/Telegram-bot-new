"""
SearchJobManager – singleton that runs search jobs as asyncio Tasks.

Each job gets its own _JobControl (stop + pause events + task handle).
The manager is wired to the Bot instance so it can edit progress messages.
"""
from __future__ import annotations

import asyncio
import io
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from loguru import logger
from telethon import TelegramClient
from telethon.sessions import StringSession

from app.config.config import settings
from app.database.database import AsyncSessionLocal
from app.database.repositories.account_repo import AccountRepository
from app.database.repositories.link_repo import LinkRepository
from app.database.repositories.search_repo import SearchRepository
from app.services.search.duplicate_detector import (
    STATUS_DUP_DB,
    STATUS_DUP_SES,
    STATUS_INVALID,
    STATUS_NEW,
    DuplicateDetector,
)
from app.services.search.search_engine import SearchEngine

_PROGRESS_INTERVAL = 15  # seconds between progress-message edits
_SESSION_DIR       = "sessions"


class _JobControl:
    def __init__(self):
        self.stop_event  = asyncio.Event()
        self.pause_event = asyncio.Event()
        self.pause_event.set()          # running (not paused) by default
        self.task: Optional[asyncio.Task] = None


class SearchJobManager:
    def __init__(self):
        self._controls: Dict[int, _JobControl] = {}
        self._bot: Optional[Bot] = None

    def set_bot(self, bot: Bot) -> None:
        self._bot = bot

    # ── public control API ─────────────────────────────────────────────

    def start(self, job_id: int, chat_id: int, message_id: int) -> None:
        """Fire a background task. Non-blocking."""
        if self.is_running(job_id):
            logger.warning(f"Job {job_id} already running")
            return
        ctrl = _JobControl()
        self._controls[job_id] = ctrl
        ctrl.task = asyncio.create_task(
            self._run(job_id, chat_id, message_id, ctrl),
            name=f"search_{job_id}",
        )
        ctrl.task.add_done_callback(lambda t: self._cleanup(job_id, t))

    def pause(self, job_id: int) -> bool:
        ctrl = self._controls.get(job_id)
        if ctrl and not ctrl.task.done():
            ctrl.pause_event.clear()
            return True
        return False

    def resume(self, job_id: int) -> bool:
        ctrl = self._controls.get(job_id)
        if ctrl and not ctrl.task.done():
            ctrl.pause_event.set()
            return True
        return False

    def stop(self, job_id: int) -> bool:
        ctrl = self._controls.get(job_id)
        if ctrl and ctrl.task and not ctrl.task.done():
            ctrl.stop_event.set()
            ctrl.pause_event.set()   # unblock if paused
            return True
        return False

    def is_running(self, job_id: int) -> bool:
        ctrl = self._controls.get(job_id)
        return bool(ctrl and ctrl.task and not ctrl.task.done())

    def is_paused(self, job_id: int) -> bool:
        ctrl = self._controls.get(job_id)
        return bool(ctrl and not ctrl.pause_event.is_set())

    # ── internal ───────────────────────────────────────────────────────

    def _cleanup(self, job_id: int, task: asyncio.Task) -> None:
        if exc := task.exception() if not task.cancelled() else None:
            logger.error(f"Job {job_id} raised: {exc}")
        self._controls.pop(job_id, None)

    async def _run(
        self,
        job_id: int,
        chat_id: int,
        msg_id: int,
        ctrl: _JobControl,
    ) -> None:
        logger.info(f"[job {job_id}] starting")

        async with AsyncSessionLocal() as db:
            search_repo  = SearchRepository(db)
            link_repo    = LinkRepository(db)
            account_repo = AccountRepository(db)

            await search_repo.set_running(job_id)
            await search_repo.set_progress_message(job_id, chat_id, msg_id)

            job = await search_repo.get_by_id(job_id)
            if not job:
                logger.error(f"Job {job_id} not found in DB")
                return

            # ── connect accounts ──────────────────────────────────
            clients: List[TelegramClient] = []
            for acc_id in (job.account_ids or []):
                acc = await account_repo.get_by_id(acc_id)
                if not acc or not acc.session_name:
                    continue
                # Use StringSession from DB (survives Railway redeploys)
                sess = StringSession(acc.session_string or "")
                client = TelegramClient(
                    sess,
                    settings.API_ID,
                    settings.API_HASH,
                )
                try:
                    await client.connect()
                    if await client.is_user_authorized():
                        clients.append(client)
                    else:
                        await client.disconnect()
                        logger.warning(f"[job {job_id}] account {acc_id} session expired")
                except Exception as e:
                    logger.error(f"[job {job_id}] connect error account {acc_id}: {e}")

            if not clients:
                await search_repo.set_failed(job_id, "لا توجد حسابات نشطة ومتصلة لتنفيذ البحث")
                await self._edit_text(
                    chat_id, msg_id,
                    "❌ فشل البحث: لا توجد حسابات نشطة ومتصلة.",
                )
                return

            # ── date range ────────────────────────────────────────
            date_from, date_to = self._resolve_dates(job)

            # ── engine + detector ─────────────────────────────────
            engine = SearchEngine(
                clients=clients,
                platforms=job.platform.value if job.platform else "both",
                search_type=job.depth.value if job.depth else "normal",
                date_from=date_from,
                date_to=date_to,
                max_results=job.max_results,
                stop_event=ctrl.stop_event,
                pause_event=ctrl.pause_event,
            )
            detector = DuplicateDetector(job_id=job_id)

            # counters (local, flushed to DB in batches + at end)
            start_time = time.monotonic()
            found = new = dup = inv = tg = wa = 0
            batch_found = batch_new = batch_dup = batch_inv = 0
            batch_tg = batch_wa = 0
            BATCH = 25
            last_upd = 0.0

            try:
                async for raw_url, source, context in engine.search():
                    if ctrl.stop_event.is_set():
                        break

                    found       += 1
                    batch_found += 1

                    status, link, is_new = await detector.process(
                        raw_url=raw_url,
                        link_repo=link_repo,
                        source_context=context,
                    )

                    if status == STATUS_INVALID:
                        inv += 1; batch_inv += 1
                    elif status in (STATUS_DUP_SES, STATUS_DUP_DB):
                        dup += 1; batch_dup += 1
                    elif is_new and link:
                        new += 1; batch_new += 1
                        if link.platform == "telegram":
                            tg += 1; batch_tg += 1
                        else:
                            wa += 1; batch_wa += 1

                    # flush counter batch to DB
                    if batch_found >= BATCH:
                        await search_repo.increment_counters(
                            job_id,
                            total=batch_found, new=batch_new,
                            duplicate=batch_dup, invalid=batch_inv,
                            telegram=batch_tg, whatsapp=batch_wa,
                        )
                        batch_found = batch_new = batch_dup = batch_inv = 0
                        batch_tg = batch_wa = 0

                    # edit progress message
                    now = time.monotonic()
                    if now - last_upd >= _PROGRESS_INTERVAL:
                        last_upd = now
                        elapsed_t = now - start_time
                        speed_t = found / max(elapsed_t, 1)
                        await self._edit_progress(
                            chat_id, msg_id, job_id,
                            found, new, dup, inv, tg, wa,
                            paused=not ctrl.pause_event.is_set(),
                            elapsed=elapsed_t,
                            speed=speed_t,
                        )

                # flush remainder
                if batch_found:
                    await search_repo.increment_counters(
                        job_id,
                        found=batch_found, new=batch_new,
                        duplicate=batch_dup, invalid=batch_inv,
                        tg=batch_tg, wa=batch_wa,
                    )

                final_status = "cancelled" if ctrl.stop_event.is_set() else "completed"
                if final_status == "cancelled":
                    await search_repo.set_cancelled(job_id)
                else:
                    await search_repo.set_completed(job_id)
                await self._edit_done(
                    chat_id, msg_id, job_id,
                    final_status, found, new, dup, inv, tg, wa,
                )

            except Exception as e:
                logger.exception(f"[job {job_id}] fatal error: {e}")
                await search_repo.set_failed(job_id, str(e))
                await self._edit_text(chat_id, msg_id, f"❌ خطأ: {str(e)[:300]}")

            finally:
                for c in clients:
                    try:
                        await c.disconnect()
                    except Exception:
                        pass

    # ── date resolution ────────────────────────────────────────────────
    @staticmethod
    def _resolve_dates(job) -> tuple[Optional[datetime], Optional[datetime]]:
        if job.period_from and job.period_to:
            return job.period_from, job.period_to
        now = datetime.now(timezone.utc)
        delta_map = {
            "today":  timedelta(days=1),
            "week":   timedelta(weeks=1),
            "month":  timedelta(days=30),
            "year":   timedelta(days=365),
        }
        delta = delta_map.get((job.period.value if job.period else None) or "month", timedelta(days=30))
        return now - delta, now

    # ── bot message helpers ────────────────────────────────────────────
    async def _edit_text(self, chat_id: int, msg_id: int, text: str) -> None:
        if not self._bot:
            return
        try:
            await self._bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass

    async def _edit_progress(
        self,
        chat_id: int, msg_id: int, job_id: int,
        found: int, new: int, dup: int, inv: int, tg: int, wa: int,
        paused: bool = False,
        elapsed: float = 0,
        current_group: str = "",
        groups_done: int = 0,
        groups_total: int = 0,
        msgs_checked: int = 0,
        speed: float = 0,
        log_lines: list = None,
    ) -> None:
        icon  = "⏸️" if paused else "🔴"
        label = "متوقف مؤقتاً" if paused else "يعمل الآن"

        # Progress bar
        pct = int(found / max(found + 1, 1) * 100)
        if groups_total > 0:
            pct = int(groups_done / groups_total * 100)
        bar_filled = int(pct / 10)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)

        # Time
        h = int(elapsed) // 3600
        m = (int(elapsed) % 3600) // 60
        s = int(elapsed) % 60
        elapsed_str = f"{h:02d}:{m:02d}:{s:02d}"

        # ETA
        eta_str = "—"
        if groups_done > 0 and groups_total > 0 and elapsed > 0:
            avg_per_group = elapsed / groups_done
            remaining = (groups_total - groups_done) * avg_per_group
            er = int(remaining)
            eta_str = f"{er//3600:02d}:{(er%3600)//60:02d}:{er%60:02d}"

        # Duplicate %
        dup_pct = round(dup / max(found, 1) * 100)

        text_parts = [
            f"{icon} البحث {label} — #JOB{job_id}",
            f"[{bar}] {pct}%",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            f"⏱️ المدة: {elapsed_str}   ⏳ المتبقي: {eta_str}",
            f"⚡ السرعة: {speed:.1f} رابط/ث",
        ]

        if groups_total > 0:
            text_parts += [
                "━━━━━━━━━━━━━━━━━━━━━━━━",
                f"📂 المجموعات: {groups_done}/{groups_total}",
            ]
        if current_group:
            text_parts.append(f"🔍 الحالية: {current_group}")
        if msgs_checked > 0:
            text_parts.append(f"💬 الرسائل المفحوصة: {msgs_checked:,}")

        text_parts += [
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            f"📊 المكتشفة:  {found:,}",
            f"✅ جديدة:     {new:,}",
            f"♻️ مكررة:     {dup:,}  ({dup_pct}%)",
            f"❌ غير صالحة: {inv:,}",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            f"📱 Telegram: {tg:,}   💬 WA: {wa:,}",
        ]

        if log_lines:
            text_parts.append("━━━━━━━━━━━━━━━━━━━━━━━━")
            text_parts.append("📋 آخر العمليات:")
            text_parts += log_lines[-5:]

        text = "\n".join(text_parts)
        kb = self._running_kb(job_id, paused)
        if not self._bot:
            return
        try:
            await self._bot.edit_message_text(
                text, chat_id=chat_id, message_id=msg_id, reply_markup=kb
            )
        except TelegramBadRequest:
            pass
        except Exception as e:
            logger.debug(f"progress edit error: {e}")

    async def _edit_done(
        self,
        chat_id: int, msg_id: int, job_id: int,
        status: str,
        found: int, new: int, dup: int, inv: int, tg: int, wa: int,
    ) -> None:
        icon  = "✅" if status == "completed" else "⛔"
        label = "اكتمل البحث" if status == "completed" else "تم إيقاف البحث"
        text = (
            f"{icon} {label}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 إجمالي المكتشفة: {found}\n"
            f"✅ روابط جديدة:    {new}\n"
            f"♻️ روابط مكررة:    {dup}\n"
            f"❌ غير صالحة:      {inv}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📱 Telegram: {tg}   💬 WhatsApp: {wa}\n"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📥 Telegram", callback_data=f"srch:export_tg:{job_id}"),
                InlineKeyboardButton(text="📥 WhatsApp", callback_data=f"srch:export_wa:{job_id}"),
            ],
            [
                InlineKeyboardButton(text="📥 الكل CSV", callback_data=f"srch:export_all:{job_id}"),
                InlineKeyboardButton(text="📊 تفاصيل",   callback_data=f"srch:view:{job_id}"),
            ],
            [
                InlineKeyboardButton(text="🔍 بحث جديد", callback_data="srch:new"),
                InlineKeyboardButton(text="⬅️ القائمة",  callback_data="back:main"),
            ],
        ])
        if not self._bot:
            return
        try:
            await self._bot.edit_message_text(
                text, chat_id=chat_id, message_id=msg_id, reply_markup=kb
            )
        except TelegramBadRequest:
            try:
                await self._bot.send_message(chat_id, text, reply_markup=kb)
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"done edit error: {e}")

    @staticmethod
    def _running_kb(job_id: int, paused: bool) -> InlineKeyboardMarkup:
        if paused:
            row = [
                InlineKeyboardButton(text="▶️ استمرار",  callback_data=f"srch:resume:{job_id}"),
                InlineKeyboardButton(text="⏹️ إيقاف",   callback_data=f"srch:stop:{job_id}"),
            ]
        else:
            row = [
                InlineKeyboardButton(text="⏸️ إيقاف مؤقت", callback_data=f"srch:pause:{job_id}"),
                InlineKeyboardButton(text="⏹️ إيقاف",       callback_data=f"srch:stop:{job_id}"),
            ]
        return InlineKeyboardMarkup(inline_keyboard=[row])

    # ── export helpers (called from bot handler) ───────────────────────
    async def build_export_file(
        self, job_id: int, platform: Optional[str]
    ) -> tuple[bytes, str]:
        """
        Return (file_bytes, filename).
        platform=None → CSV of all links.
        platform='telegram'|'whatsapp' → TXT of URLs.
        """
        from datetime import datetime
        stamp = datetime.now().strftime("%Y%m%d_%H%M")

        async with AsyncSessionLocal() as db:
            link_repo = LinkRepository(db)

            if platform is None:
                # CSV
                links = await link_repo.list_by_job(job_id)
                lines = ["Platform,Type,URL,FirstSeen,LastSeen,SeenCount"]
                for lk in links:
                    fs = lk.first_seen_at.strftime("%Y-%m-%d %H:%M") if lk.first_seen_at else ""
                    ls = lk.last_seen_at.strftime("%Y-%m-%d %H:%M") if lk.last_seen_at else ""
                    lines.append(
                        f"{lk.platform},{lk.link_type},{lk.normalized_url},{fs},{ls},{lk.seen_count}"
                    )
                content = "\n".join(lines).encode("utf-8")
                name    = f"all_links_{stamp}.csv"
            else:
                # TXT
                urls    = await link_repo.export_urls(job_id, platform=platform)
                content = "\n".join(urls).encode("utf-8")
                name    = f"{platform}_links_{stamp}.txt"

        return content, name


# ── global singleton ───────────────────────────────────────────────────
search_job_manager = SearchJobManager()
