"""
LinkRepository — insert links with duplicate detection at the DB layer.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.search import (
    DiscoveredLink,
    DuplicateRecord,
    LinkPlatform,
    LinkStatus,
    LinkType,
)


class LinkRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── insert new / record duplicate ────────────────────────────────────

    async def upsert_link(
        self,
        *,
        platform: LinkPlatform,
        link_type: LinkType,
        original_url: str,
        normalized_url: str,
        url_hash: str,
        search_id: Optional[int] = None,
        source_account_id: Optional[int] = None,
        source: Optional[str] = None,
        title: Optional[str] = None,
        username: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Tuple[bool, DiscoveredLink]:
        """
        Try to insert a new link.
        Returns (is_new, link_object).

        If a link with the same (platform, url_hash) already exists:
          - records a DuplicateRecord
          - returns (False, existing_link)

        Uses the DB UNIQUE constraint as the ultimate guard, so even
        two concurrent workers cannot produce duplicates.
        """
        # 1. Application-level check (avoids a round-trip on the hot path)
        existing = await self.get_by_hash(platform, url_hash)
        if existing is not None:
            await self._record_duplicate(
                existing_link=existing,
                original_url=original_url,
                normalized_url=normalized_url,
                url_hash=url_hash,
                platform=platform,
                search_id=search_id,
                source_account_id=source_account_id,
                source=source,
            )
            return False, existing

        # 2. Attempt insert — the DB UNIQUE constraint catches races
        link = DiscoveredLink(
            platform=platform,
            link_type=link_type,
            original_url=original_url,
            normalized_url=normalized_url,
            url_hash=url_hash,
            search_id=search_id,
            source_account_id=source_account_id,
            source=source,
            title=title,
            username=username,
            metadata_json=metadata,
            status=LinkStatus.VALID,
        )
        self.db.add(link)
        try:
            await self.db.commit()
            await self.db.refresh(link)
            return True, link
        except IntegrityError:
            await self.db.rollback()
            # Someone else inserted the same hash concurrently
            existing = await self.get_by_hash(platform, url_hash)
            if existing:
                await self._record_duplicate(
                    existing_link=existing,
                    original_url=original_url,
                    normalized_url=normalized_url,
                    url_hash=url_hash,
                    platform=platform,
                    search_id=search_id,
                    source_account_id=source_account_id,
                    source=source,
                )
                return False, existing
            raise  # Unexpected — re-raise

    async def _record_duplicate(
        self,
        *,
        existing_link: DiscoveredLink,
        original_url: str,
        normalized_url: str,
        url_hash: str,
        platform: LinkPlatform,
        search_id: Optional[int],
        source_account_id: Optional[int],
        source: Optional[str],
    ) -> None:
        rec = DuplicateRecord(
            original_url=original_url,
            normalized_url=normalized_url,
            url_hash=url_hash,
            platform=platform,
            search_id=search_id,
            existing_link_id=existing_link.id,
            source_account_id=source_account_id,
            source=source,
        )
        self.db.add(rec)
        await self.db.commit()

    # ── fetch ────────────────────────────────────────────────────────────

    async def get_by_hash(
        self, platform: LinkPlatform, url_hash: str
    ) -> Optional[DiscoveredLink]:
        result = await self.db.execute(
            select(DiscoveredLink).where(
                DiscoveredLink.platform == platform,
                DiscoveredLink.url_hash == url_hash,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_search(
        self, search_id: int, *, new_only: bool = False, limit: int = 5000
    ) -> List[DiscoveredLink]:
        q = select(DiscoveredLink).where(DiscoveredLink.search_id == search_id)
        if new_only:
            q = q.where(DiscoveredLink.is_duplicate == False)  # noqa: E712
        q = q.order_by(DiscoveredLink.created_at.asc()).limit(limit)
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def list_by_search_and_platform(
        self, search_id: int, platform: LinkPlatform, *, new_only: bool = True
    ) -> List[DiscoveredLink]:
        q = (
            select(DiscoveredLink)
            .where(
                DiscoveredLink.search_id == search_id,
                DiscoveredLink.platform == platform,
            )
            .order_by(DiscoveredLink.created_at.asc())
        )
        if new_only:
            q = q.where(DiscoveredLink.is_duplicate == False)  # noqa: E712
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def count_duplicates_for_search(self, search_id: int) -> int:
        from sqlalchemy import func as sqlfunc

        result = await self.db.scalar(
            select(sqlfunc.count(DuplicateRecord.id)).where(
                DuplicateRecord.search_id == search_id
            )
        )
        return result or 0
