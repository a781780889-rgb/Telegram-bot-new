"""
SearchJobRepository — all database operations for search jobs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.search import SearchJob, SearchStatus


class SearchJobRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── create ──────────────────────────────────────────────────────────

    async def create(
        self,
        user_id: int,
        platform: str,
        depth: str,
        period: str,
        account_ids: list,
        link_types_config: dict,
        max_results: int = 1000,
        dedup_enabled: bool = True,
        compare_db: bool = True,
        save_new: bool = True,
        skip_invalid: bool = True,
        period_from: Optional[datetime] = None,
        period_to: Optional[datetime] = None,
        chat_id: Optional[int] = None,
        message_id: Optional[int] = None,
    ) -> SearchJob:
        from app.database.models.search import SearchPlatform, SearchDepth, SearchPeriod

        job = SearchJob(
            user_id=user_id,
            platform=SearchPlatform(platform),
            depth=SearchDepth(depth),
            period=SearchPeriod(period),
            account_ids=account_ids,
            link_types_config=link_types_config,
            max_results=max_results,
            dedup_enabled=dedup_enabled,
            compare_db=compare_db,
            save_new=save_new,
            skip_invalid=skip_invalid,
            period_from=period_from,
            period_to=period_to,
            chat_id=chat_id,
            message_id=message_id,
            status=SearchStatus.PENDING,
        )
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)
        return job

    # ── fetch ────────────────────────────────────────────────────────────

    async def get_by_id(self, job_id: int) -> Optional[SearchJob]:
        result = await self.db.execute(select(SearchJob).where(SearchJob.id == job_id))
        return result.scalar_one_or_none()

    async def list_by_user(
        self, user_id: int, limit: int = 20, offset: int = 0
    ) -> List[SearchJob]:
        result = await self.db.execute(
            select(SearchJob)
            .where(SearchJob.user_id == user_id)
            .order_by(SearchJob.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_active(self) -> List[SearchJob]:
        result = await self.db.execute(
            select(SearchJob).where(
                SearchJob.status.in_([SearchStatus.RUNNING, SearchStatus.PAUSED])
            )
        )
        return list(result.scalars().all())

    # ── status transitions ───────────────────────────────────────────────

    async def set_running(self, job_id: int) -> None:
        await self.db.execute(
            update(SearchJob)
            .where(SearchJob.id == job_id)
            .values(status=SearchStatus.RUNNING, started_at=datetime.now(timezone.utc))
        )
        await self.db.commit()

    async def set_paused(self, job_id: int) -> None:
        await self.db.execute(
            update(SearchJob).where(SearchJob.id == job_id).values(status=SearchStatus.PAUSED)
        )
        await self.db.commit()

    async def set_resumed(self, job_id: int) -> None:
        await self.db.execute(
            update(SearchJob).where(SearchJob.id == job_id).values(status=SearchStatus.RUNNING)
        )
        await self.db.commit()

    async def set_completed(self, job_id: int) -> None:
        await self.db.execute(
            update(SearchJob)
            .where(SearchJob.id == job_id)
            .values(status=SearchStatus.COMPLETED, finished_at=datetime.now(timezone.utc))
        )
        await self.db.commit()

    async def set_failed(self, job_id: int, error: str) -> None:
        await self.db.execute(
            update(SearchJob)
            .where(SearchJob.id == job_id)
            .values(
                status=SearchStatus.FAILED,
                finished_at=datetime.now(timezone.utc),
                error_log=error[:2000],
            )
        )
        await self.db.commit()

    async def set_cancelled(self, job_id: int) -> None:
        await self.db.execute(
            update(SearchJob)
            .where(SearchJob.id == job_id)
            .values(status=SearchStatus.CANCELLED, finished_at=datetime.now(timezone.utc))
        )
        await self.db.commit()

    # ── counters ─────────────────────────────────────────────────────────

    async def increment_counters(
        self,
        job_id: int,
        *,
        total: int = 0,
        new: int = 0,
        duplicate: int = 0,
        invalid: int = 0,
        telegram: int = 0,
        whatsapp: int = 0,
    ) -> None:
        """Increment counters atomically — safe to call from the worker loop."""
        job = await self.get_by_id(job_id)
        if job is None:
            return
        await self.db.execute(
            update(SearchJob)
            .where(SearchJob.id == job_id)
            .values(
                found_total     = SearchJob.found_total     + total,
                found_new       = SearchJob.found_new       + new,
                found_duplicate = SearchJob.found_duplicate + duplicate,
                found_invalid   = SearchJob.found_invalid   + invalid,
                found_telegram  = SearchJob.found_telegram  + telegram,
                found_whatsapp  = SearchJob.found_whatsapp  + whatsapp,
            )
        )
        await self.db.commit()

    async def set_message_ref(self, job_id: int, chat_id: int, message_id: int) -> None:
        await self.db.execute(
            update(SearchJob)
            .where(SearchJob.id == job_id)
            .values(chat_id=chat_id, message_id=message_id)
        )
        await self.db.commit()

    # ── stats ────────────────────────────────────────────────────────────

    async def get_global_stats(self) -> dict:
        from sqlalchemy import func as sqlfunc
        from app.database.models.search import DiscoveredLink, LinkPlatform

        tg_count = await self.db.scalar(
            select(sqlfunc.count(DiscoveredLink.id)).where(
                DiscoveredLink.platform == LinkPlatform.TELEGRAM
            )
        )
        wa_count = await self.db.scalar(
            select(sqlfunc.count(DiscoveredLink.id)).where(
                DiscoveredLink.platform == LinkPlatform.WHATSAPP
            )
        )
        search_count = await self.db.scalar(select(sqlfunc.count(SearchJob.id)))
        return {
            "total_links": (tg_count or 0) + (wa_count or 0),
            "telegram_links": tg_count or 0,
            "whatsapp_links": wa_count or 0,
            "total_searches": search_count or 0,
        }
