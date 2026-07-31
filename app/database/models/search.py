"""
Search system database models.

Tables:
  search_jobs        — one record per user-initiated search operation
  discovered_links   — every unique link found (UNIQUE on platform+url_hash)
  duplicate_records  — occurrence log for links that already existed
"""

import enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.database import Base


# ──────────────────────────────────────────────
# Enum definitions
# ──────────────────────────────────────────────

class SearchDepth(enum.Enum):
    FAST   = "fast"
    NORMAL = "normal"
    DEEP   = "deep"


class SearchPlatform(enum.Enum):
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    BOTH     = "both"


class SearchPeriod(enum.Enum):
    DAY    = "day"
    WEEK   = "week"
    MONTH  = "month"
    YEAR   = "year"
    CUSTOM = "custom"


class SearchStatus(enum.Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    PAUSED    = "paused"
    COMPLETED = "completed"
    FAILED    = "failed"
    CANCELLED = "cancelled"


class LinkPlatform(enum.Enum):
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"


class LinkType(enum.Enum):
    # Telegram
    PUBLIC_GROUP  = "public_group"
    PRIVATE_GROUP = "private_group"
    CHANNEL       = "channel"
    # WhatsApp
    WA_GROUP      = "wa_group"
    WA_CHANNEL    = "wa_channel"
    # Fallback
    UNKNOWN       = "unknown"


class LinkStatus(enum.Enum):
    VALID   = "valid"
    INVALID = "invalid"
    UNKNOWN = "unknown"


# ──────────────────────────────────────────────
# SearchJob
# ──────────────────────────────────────────────

class SearchJob(Base):
    __tablename__ = "search_jobs"

    id      = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)

    # ── configuration ──
    platform          = Column(Enum(SearchPlatform), nullable=False)
    depth             = Column(Enum(SearchDepth),    nullable=False, default=SearchDepth.NORMAL)
    period            = Column(Enum(SearchPeriod),   nullable=False, default=SearchPeriod.WEEK)
    period_from       = Column(DateTime(timezone=True), nullable=True)
    period_to         = Column(DateTime(timezone=True), nullable=True)

    # JSON list of account IDs selected for this job
    account_ids       = Column(JSON, nullable=True)

    # JSON dict with link-type toggles, e.g.
    #   {"tg_groups": true, "tg_channels": true, "tg_private": false,
    #    "wa_groups": true, "wa_channels": true}
    link_types_config = Column(JSON, nullable=True)

    max_results       = Column(BigInteger, default=1000)
    dedup_enabled     = Column(Boolean, default=True)
    compare_db        = Column(Boolean, default=True)
    save_new          = Column(Boolean, default=True)
    skip_invalid      = Column(Boolean, default=True)

    # ── status ──
    status = Column(Enum(SearchStatus), default=SearchStatus.PENDING, index=True)

    # ── live counters (updated incrementally during the run) ──
    found_total     = Column(BigInteger, default=0)
    found_new       = Column(BigInteger, default=0)
    found_duplicate = Column(BigInteger, default=0)
    found_invalid   = Column(BigInteger, default=0)
    found_telegram  = Column(BigInteger, default=0)
    found_whatsapp  = Column(BigInteger, default=0)

    # ── timing ──
    started_at  = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    error_log = Column(Text, nullable=True)

    # ── bot message reference (for live progress editing) ──
    chat_id    = Column(BigInteger, nullable=True)
    message_id = Column(BigInteger, nullable=True)


# ──────────────────────────────────────────────
# DiscoveredLink
# ──────────────────────────────────────────────

class DiscoveredLink(Base):
    """
    One row per unique link.
    UNIQUE constraint on (platform, url_hash) is enforced at both the
    application layer and the database layer to survive concurrent jobs.
    """
    __tablename__ = "discovered_links"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    platform  = Column(Enum(LinkPlatform), nullable=False)
    link_type = Column(Enum(LinkType), default=LinkType.UNKNOWN)

    original_url   = Column(Text,          nullable=False)
    normalized_url = Column(Text,          nullable=False)
    url_hash       = Column(String(64),    nullable=False)  # SHA-256 of normalized_url

    title    = Column(String, nullable=True)
    username = Column(String, nullable=True)

    source            = Column(String,    nullable=True)   # e.g. "telegram_search", "web_scrape"
    source_account_id = Column(BigInteger, ForeignKey("accounts.id"), nullable=True)

    search_id = Column(BigInteger, ForeignKey("search_jobs.id"), nullable=True)

    status       = Column(Enum(LinkStatus), default=LinkStatus.VALID)
    is_duplicate = Column(Boolean, default=False)

    first_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    metadata_json = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        # Database-level uniqueness — survives concurrent inserts
        UniqueConstraint("platform", "url_hash", name="uq_link_platform_hash"),
        Index("ix_link_platform_hash",  "platform", "url_hash"),
        Index("ix_link_search_id",      "search_id"),
        Index("ix_link_platform",       "platform"),
        Index("ix_link_created_at",     "created_at"),
        Index("ix_link_status",         "status"),
    )


# ──────────────────────────────────────────────
# DuplicateRecord
# ──────────────────────────────────────────────

class DuplicateRecord(Base):
    """
    Every time a link is discovered but already exists in discovered_links,
    an occurrence is logged here.  This gives a full history of 'how many
    times, when, and from which search/account was the link seen again'.
    """
    __tablename__ = "duplicate_records"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    original_url   = Column(Text,       nullable=False)
    normalized_url = Column(Text,       nullable=False)
    url_hash       = Column(String(64), nullable=False)
    platform       = Column(Enum(LinkPlatform), nullable=False)

    search_id         = Column(BigInteger, ForeignKey("search_jobs.id"),      nullable=True, index=True)
    existing_link_id  = Column(BigInteger, ForeignKey("discovered_links.id"), nullable=True, index=True)
    source_account_id = Column(BigInteger, ForeignKey("accounts.id"),         nullable=True)

    source      = Column(String, nullable=True)
    detected_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
