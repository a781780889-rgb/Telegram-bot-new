"""Repository for Link and DuplicateLink models.

save_link() is the critical path: it must never insert a duplicate
and must handle race conditions from concurrent workers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, desc, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.search_models import DuplicateLink, Link


class LinkRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ──────────────────────────────────────────────────────────────
    # Core insert with dedup
    # ──────────────────────────────────────────────────────────────
    async def save_link(
        self,
        platform: str,
        link_type: str,
        original_url: str,
        normalized_url: str,
        url_hash: str,
        search_job_id: Optional[int] = None,
        source_account_id: Optional[int] = None,
        username: Optional[str] = None,
        invite_code: Optional[str] = None,
        source_context: Optional[str] = None,
    ) -> tuple[Link, bool]:
        """
        Returns (link, is_new).
        If the (platform, url_hash) pair already exists the existing
        record is returned with is_new=False.
        Handles the race-condition case via IntegrityError catch.
        """
        # ── 1. optimistic read ────────────────────────────────────
        existing = await self._get_by_hash(platform, url_hash)
        if existing:
            # Bump last_seen / seen_count
            await self.db.execute(
                update(Link)
                .where(Link.id == existing.id)
                .values(
                    last_seen_at=datetime.now(timezone.utc),
                    seen_count=Link.seen_count + 1,
                )
            )
            await self.db.commit()
            return existing, False

        # ── 2. attempt insert ─────────────────────────────────────
        link = Link(
            platform=platform,
            link_type=link_type,
            original_url=original_url,
            normalized_url=normalized_url,
            url_hash=url_hash,
            search_job_id=search_job_id,
            source_account_id=source_account_id,
            username=username,
            invite_code=invite_code,
            source_context=(source_context or "")[:500],
            status="unknown",
        )
        try:
            self.db.add(link)
            await self.db.commit()
            await self.db.refresh(link)
            return link, True

        except IntegrityError:
            # ── 3. concurrent insert won the race; fetch theirs ───
            await self.db.rollback()
            existing = await self._get_by_hash(platform, url_hash)
            if existing:
                return existing, False
            raise  # Should never reach here

    # ──────────────────────────────────────────────────────────────
    # Record a duplicate occurrence
    # ──────────────────────────────────────────────────────────────
    async def record_duplicate(
        self,
        original_url: str,
        normalized_url: str,
        url_hash: str,
        platform: str,
        existing_link_id: int,
        search_job_id: Optional[int] = None,
        source_account_id: Optional[int] = None,
    ) -> DuplicateLink:
        dup = DuplicateLink(
            original_url=original_url,
            normalized_url=normalized_url,
            url_hash=url_hash,
            platform=platform,
            existing_link_id=existing_link_id,
            search_job_id=search_job_id,
            source_account_id=source_account_id,
        )
        self.db.add(dup)
        await self.db.commit()
        return dup

    # ──────────────────────────────────────────────────────────────
    # Reads
    # ──────────────────────────────────────────────────────────────
    async def _get_by_hash(self, platform: str, url_hash: str) -> Optional[Link]:
        result = await self.db.execute(
            select(Link).where(
                and_(
                    Link.platform == platform,
                    Link.url_hash == url_hash,
                    Link.is_deleted.is_(False),
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_by_job(
        self,
        job_id: int,
        platform: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[Link]:
        q = select(Link).where(
            Link.search_job_id == job_id,
            Link.is_deleted.is_(False),
        )
        if platform:
            q = q.where(Link.platform == platform)
        q = q.order_by(Link.first_seen_at).limit(limit).offset(offset)
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def export_urls(
        self, job_id: int, platform: Optional[str] = None
    ) -> list[str]:
        """Return only the normalized URL strings for export files."""
        q = select(Link.normalized_url).where(
            Link.search_job_id == job_id,
            Link.is_deleted.is_(False),
        )
        if platform:
            q = q.where(Link.platform == platform)
        q = q.order_by(Link.first_seen_at)
        result = await self.db.execute(q)
        return [row[0] for row in result.all()]

    async def count_by_job(
        self, job_id: int, platform: Optional[str] = None
    ) -> int:
        q = select(func.count(Link.id)).where(
            Link.search_job_id == job_id,
            Link.is_deleted.is_(False),
        )
        if platform:
            q = q.where(Link.platform == platform)
        return (await self.db.scalar(q)) or 0

    async def get_user_link_stats(self, user_id: int) -> dict:
        """Total links stats for a user across all jobs."""
        from app.database.models.search_models import SearchJob

        def _count(platform: str):
            return (
                select(func.count(Link.id))
                .join(SearchJob, Link.search_job_id == SearchJob.id)
                .where(
                    SearchJob.user_id == user_id,
                    Link.platform == platform,
                    Link.is_deleted.is_(False),
                )
            )

        tg = (await self.db.scalar(_count("telegram"))) or 0
        wa = (await self.db.scalar(_count("whatsapp"))) or 0
        return {"total": tg + wa, "telegram": tg, "whatsapp": wa}

    async def upsert_link(
        self,
        platform,
        link_type,
        original_url: str,
        normalized_url: str,
        url_hash: str,
        search_id: int | None = None,
        source_account_id: int | None = None,
        source: str | None = None,
        username: str | None = None,
    ) -> tuple:
        """Alias used by engine.py — delegates to save_link."""
        link, is_new = await self.save_link(
            platform=platform,
            link_type=link_type,
            original_url=original_url,
            normalized_url=normalized_url,
            url_hash=url_hash,
            search_job_id=search_id,
            source_account_id=source_account_id,
            username=username,
        )
        return is_new, link
