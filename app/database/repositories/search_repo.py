"""Repository for SearchJob CRUD and counter updates."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.search_models import SearchJob, SearchStatus, SearchPlatform, SearchDepth, SearchPeriod


class SearchJobRepository:
    """Used by engine.py and handlers."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Create ─────────────────────────────────────────────────────────────

    async def create(
        self,
        user_id: int,
        platform: SearchPlatform,
        depth: SearchDepth,
        period: SearchPeriod,
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
        job = SearchJob(
            user_id=user_id,
            platform=platform,
            depth=depth,
            period=period,
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

    # ── Read ───────────────────────────────────────────────────────────────

    async def get_by_id(self, job_id: int) -> Optional[SearchJob]:
        result = await self.db.execute(
            select(SearchJob).where(SearchJob.id == job_id)
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: int, limit: int = 20) -> list[SearchJob]:
        result = await self.db.execute(
            select(SearchJob)
            .where(SearchJob.user_id == user_id)
            .order_by(desc(SearchJob.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())

    # ── Status updates ─────────────────────────────────────────────────────

    async def set_running(self, job_id: int) -> None:
        await self.db.execute(
            update(SearchJob).where(SearchJob.id == job_id).values(
                status=SearchStatus.RUNNING,
                started_at=datetime.now(timezone.utc),
            )
        )
        await self.db.commit()

    async def set_completed(self, job_id: int) -> None:
        await self.db.execute(
            update(SearchJob).where(SearchJob.id == job_id).values(
                status=SearchStatus.COMPLETED,
                finished_at=datetime.now(timezone.utc),
            )
        )
        await self.db.commit()

    async def set_cancelled(self, job_id: int) -> None:
        await self.db.execute(
            update(SearchJob).where(SearchJob.id == job_id).values(
                status=SearchStatus.CANCELLED,
                finished_at=datetime.now(timezone.utc),
            )
        )
        await self.db.commit()

    async def set_failed(self, job_id: int, error: str) -> None:
        await self.db.execute(
            update(SearchJob).where(SearchJob.id == job_id).values(
                status=SearchStatus.FAILED,
                finished_at=datetime.now(timezone.utc),
                error_log=error,
            )
        )
        await self.db.commit()

    async def set_paused(self, job_id: int) -> None:
        await self.db.execute(
            update(SearchJob).where(SearchJob.id == job_id).values(
                status=SearchStatus.PAUSED,
            )
        )
        await self.db.commit()

    # ── Counter increments (atomic via SQL expression) ─────────────────────

    async def increment_counters(
        self,
        job_id: int,
        total: int = 0,
        new: int = 0,
        duplicate: int = 0,
        invalid: int = 0,
        telegram: int = 0,
        whatsapp: int = 0,
    ) -> None:
        if not any([total, new, duplicate, invalid, telegram, whatsapp]):
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

    # ── Progress message ───────────────────────────────────────────────────

    async def set_progress_message(self, job_id: int, chat_id: int, message_id: int) -> None:
        await self.db.execute(
            update(SearchJob).where(SearchJob.id == job_id).values(
                chat_id=chat_id,
                message_id=message_id,
            )
        )
        await self.db.commit()

    # ── Stats ──────────────────────────────────────────────────────────────

    async def get_user_stats(self, user_id: int) -> dict:
        from sqlalchemy import func as sqlfunc
        result = await self.db.execute(
            select(
                sqlfunc.count(SearchJob.id).label("total"),
                sqlfunc.sum(SearchJob.found_total).label("total_found"),
                sqlfunc.sum(SearchJob.found_new).label("total_new"),
                sqlfunc.sum(SearchJob.found_duplicate).label("total_dup"),
            ).where(SearchJob.user_id == user_id)
        )
        row = result.one()
        return {
            "total_jobs":  row.total or 0,
            "total_found": int(row.total_found or 0),
            "total_new":   int(row.total_new or 0),
            "total_dup":   int(row.total_dup or 0),
        }


# Alias للتوافق مع أي كود قديم يستخدم SearchRepository
SearchRepository = SearchJobRepository
