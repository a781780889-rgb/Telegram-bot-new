"""Repository for SearchJob CRUD and counter updates."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.search_models import SearchJob


class SearchRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ──────────────────────────────────────────────────────────────
    # Create
    # ──────────────────────────────────────────────────────────────
    async def create(
        self,
        user_id: int,
        account_ids: list[int],
        platforms: str,
        link_types: list[str],
        search_type: str,
        date_range: Optional[str],
        date_from: Optional[datetime],
        date_to: Optional[datetime],
        max_results: int,
        dedup_enabled: bool = True,
        compare_with_db: bool = True,
    ) -> SearchJob:
        job = SearchJob(
            user_id=user_id,
            account_ids=account_ids,
            platforms=platforms,
            link_types=link_types,
            search_type=search_type,
            date_range=date_range,
            date_from=date_from,
            date_to=date_to,
            max_results=max_results,
            dedup_enabled=dedup_enabled,
            compare_with_db=compare_with_db,
            status="pending",
        )
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)
        return job

    # ──────────────────────────────────────────────────────────────
    # Read
    # ──────────────────────────────────────────────────────────────
    async def get_by_id(self, job_id: int) -> Optional[SearchJob]:
        result = await self.db.execute(
            select(SearchJob).where(SearchJob.id == job_id)
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self, user_id: int, limit: int = 20
    ) -> list[SearchJob]:
        result = await self.db.execute(
            select(SearchJob)
            .where(SearchJob.user_id == user_id)
            .order_by(desc(SearchJob.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())

    # ──────────────────────────────────────────────────────────────
    # Status updates
    # ──────────────────────────────────────────────────────────────
    async def update_status(
        self,
        job_id: int,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        values: dict = {"status": status}
        if status == "running":
            values["started_at"] = datetime.now(timezone.utc)
        elif status in ("completed", "failed", "cancelled"):
            values["completed_at"] = datetime.now(timezone.utc)
        if error_message is not None:
            values["error_message"] = error_message

        await self.db.execute(
            update(SearchJob).where(SearchJob.id == job_id).values(**values)
        )
        await self.db.commit()

    # ──────────────────────────────────────────────────────────────
    # Counter increments (atomic via SQL expression)
    # ──────────────────────────────────────────────────────────────
    async def increment_counters(
        self,
        job_id: int,
        found: int = 0,
        new: int = 0,
        duplicate: int = 0,
        invalid: int = 0,
        tg: int = 0,
        wa: int = 0,
    ) -> None:
        if not any([found, new, duplicate, invalid, tg, wa]):
            return
        await self.db.execute(
            update(SearchJob)
            .where(SearchJob.id == job_id)
            .values(
                found_count=SearchJob.found_count + found,
                new_count=SearchJob.new_count + new,
                duplicate_count=SearchJob.duplicate_count + duplicate,
                invalid_count=SearchJob.invalid_count + invalid,
                tg_count=SearchJob.tg_count + tg,
                wa_count=SearchJob.wa_count + wa,
            )
        )
        await self.db.commit()

    # ──────────────────────────────────────────────────────────────
    # Progress metadata
    # ──────────────────────────────────────────────────────────────
    async def set_progress_message(
        self, job_id: int, chat_id: int, message_id: int
    ) -> None:
        await self.db.execute(
            update(SearchJob)
            .where(SearchJob.id == job_id)
            .values(progress_chat_id=chat_id, progress_message_id=message_id)
        )
        await self.db.commit()

    async def set_current_source(
        self, job_id: int, source: str, done: int, total: int
    ) -> None:
        await self.db.execute(
            update(SearchJob)
            .where(SearchJob.id == job_id)
            .values(current_source=source, sources_done=done, sources_total=total)
        )
        await self.db.commit()

    # ──────────────────────────────────────────────────────────────
    # Stats for a user
    # ──────────────────────────────────────────────────────────────
    async def get_user_stats(self, user_id: int) -> dict:
        from sqlalchemy import func as sqlfunc
        result = await self.db.execute(
            select(
                sqlfunc.count(SearchJob.id).label("total"),
                sqlfunc.sum(SearchJob.new_count).label("total_new"),
                sqlfunc.sum(SearchJob.duplicate_count).label("total_dup"),
                sqlfunc.sum(SearchJob.found_count).label("total_found"),
            ).where(SearchJob.user_id == user_id)
        )
        row = result.one()
        return {
            "total_jobs": row.total or 0,
            "total_new": int(row.total_new or 0),
            "total_dup": int(row.total_dup or 0),
            "total_found": int(row.total_found or 0),
        }
