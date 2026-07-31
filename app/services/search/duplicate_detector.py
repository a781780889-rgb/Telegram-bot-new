"""
Two-layer duplicate detection:

Layer 1 – in-memory set (O(1))
    Catches duplicates found multiple times within the same search
    session without touching the database.

Layer 2 – database unique constraint (atomic)
    Catches links already discovered in previous sessions.
    The DB unique index on (platform, url_hash) is the ultimate
    authority; IntegrityError is handled in save_link().
"""
from __future__ import annotations

import asyncio
from typing import Optional, Tuple

from app.database.models.search_models import Link
from app.database.repositories.link_repo import LinkRepository
from app.services.search.link_validator import validate_and_classify
from app.services.search.url_normalizer import fingerprint

# status strings returned by process()
STATUS_NEW       = "new"
STATUS_DUP_SES   = "duplicate_session"   # seen earlier in this search run
STATUS_DUP_DB    = "duplicate_db"        # existed in DB from a previous run
STATUS_INVALID   = "invalid"


class DuplicateDetector:
    """
    One instance per SearchJob. Create it fresh for every job so that
    the in-memory set resets between jobs.
    """

    def __init__(self, job_id: Optional[int] = None):
        self.job_id = job_id
        self._seen: set[str] = set()   # fingerprints seen this session
        self._lock = asyncio.Lock()

    async def process(
        self,
        raw_url: str,
        link_repo: LinkRepository,
        source_account_id: Optional[int] = None,
        source_context: Optional[str] = None,
    ) -> Tuple[str, Optional[Link], bool]:
        """
        Full dedup pipeline for one raw URL.

        Returns:
            (status, link_or_None, is_new)

        Guarantee: a (platform, url_hash) pair is inserted into the DB
        at most once, even under concurrent workers.
        """
        # ── Step 1: validate + normalise ──────────────────────────
        is_valid, platform, link_type, normalised = validate_and_classify(raw_url)
        if not is_valid or normalised is None:
            return STATUS_INVALID, None, False

        fp = fingerprint(normalised)

        # ── Step 2: in-memory check ───────────────────────────────
        async with self._lock:
            if fp in self._seen:
                return STATUS_DUP_SES, None, False
            self._seen.add(fp)

        # ── Step 3: DB insert (handles race via IntegrityError) ───
        link, is_new = await link_repo.save_link(
            platform=platform,
            link_type=link_type or "unknown",
            original_url=raw_url,
            normalized_url=normalised,
            url_hash=fp,
            search_job_id=self.job_id,
            source_account_id=source_account_id,
            source_context=source_context,
        )

        if not is_new:
            # ── Step 4: record duplicate occurrence ───────────────
            await link_repo.record_duplicate(
                original_url=raw_url,
                normalized_url=normalised,
                url_hash=fp,
                platform=platform,
                existing_link_id=link.id,
                search_job_id=self.job_id,
                source_account_id=source_account_id,
            )
            return STATUS_DUP_DB, link, False

        return STATUS_NEW, link, True
