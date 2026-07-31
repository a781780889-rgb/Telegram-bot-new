"""
Search-related SQLAlchemy models + Enums.
All search-related imports should come from this file only.
"""
import enum

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime,
    Enum, ForeignKey, Index, Integer, JSON,
    String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.database import Base


# ── Enums ──────────────────────────────────────────────────────────────────

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
    PUBLIC_GROUP  = "public_group"
    PRIVATE_GROUP = "private_group"
    CHANNEL       = "channel"
    WA_GROUP      = "wa_group"
    WA_CHANNEL    = "wa_channel"
    UNKNOWN       = "unknown"


class LinkStatus(enum.Enum):
    VALID   = "valid"
    INVALID = "invalid"
    UNKNOWN = "unknown"


# ── SearchJob ──────────────────────────────────────────────────────────────

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
    account_ids       = Column(JSON, nullable=True)
    link_types_config = Column(JSON, nullable=True)
    max_results       = Column(BigInteger, default=1000)
    dedup_enabled     = Column(Boolean, default=True)
    compare_db        = Column(Boolean, default=True)
    save_new          = Column(Boolean, default=True)
    skip_invalid      = Column(Boolean, default=True)

    # ── status ──
    status = Column(Enum(SearchStatus), default=SearchStatus.PENDING, index=True)

    # ── live counters ──
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
    error_log   = Column(Text, nullable=True)

    # ── bot message reference ──
    chat_id    = Column(BigInteger, nullable=True)
    message_id = Column(BigInteger, nullable=True)

    # ── relationships ──
    links           = relationship("Link",          back_populates="search_job", lazy="dynamic")
    duplicate_links = relationship("DuplicateLink", back_populates="search_job", lazy="dynamic")


# ── Link ───────────────────────────────────────────────────────────────────

class Link(Base):
    __tablename__ = "links"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    platform       = Column(Enum(LinkPlatform), nullable=False, index=True)
    link_type      = Column(Enum(LinkType),     default=LinkType.UNKNOWN, index=True)
    original_url   = Column(Text,        nullable=False)
    normalized_url = Column(Text,        nullable=False)
    url_hash       = Column(String(64),  nullable=False)

    title             = Column(String,    nullable=True)
    username          = Column(String,    nullable=True, index=True)
    invite_code       = Column(String,    nullable=True)
    source_context    = Column(Text,      nullable=True)
    source            = Column(String,    nullable=True)
    source_account_id = Column(BigInteger, ForeignKey("accounts.id"), nullable=True)
    search_job_id     = Column(BigInteger, ForeignKey("search_jobs.id"), nullable=True, index=True)

    status     = Column(Enum(LinkStatus), default=LinkStatus.UNKNOWN)
    is_deleted = Column(Boolean, default=False)

    first_seen_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    last_seen_at  = Column(DateTime(timezone=True), server_default=func.now())
    seen_count    = Column(Integer, default=1)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())

    # ── relationships ──
    search_job        = relationship("SearchJob",    back_populates="links")
    duplicate_records = relationship("DuplicateLink", back_populates="existing_link")

    __table_args__ = (
        UniqueConstraint("platform", "url_hash", name="uq_link_platform_hash"),
        Index("ix_link_platform_hash",  "platform", "url_hash"),
        Index("ix_link_type_platform",  "link_type", "platform"),
        Index("ix_link_first_seen",     "first_seen_at"),
    )


# ── DuplicateLink ──────────────────────────────────────────────────────────

class DuplicateLink(Base):
    __tablename__ = "duplicate_links"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    original_url   = Column(Text,       nullable=False)
    normalized_url = Column(Text,       nullable=False)
    url_hash       = Column(String(64), nullable=False)
    platform       = Column(Enum(LinkPlatform), nullable=False)

    search_job_id     = Column(BigInteger, ForeignKey("search_jobs.id"), nullable=True, index=True)
    existing_link_id  = Column(BigInteger, ForeignKey("links.id"),       nullable=True)
    source_account_id = Column(BigInteger, ForeignKey("accounts.id"),    nullable=True)
    source            = Column(String, nullable=True)

    detected_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # ── relationships ──
    search_job    = relationship("SearchJob", back_populates="duplicate_links")
    existing_link = relationship("Link",       back_populates="duplicate_records")

    __table_args__ = (
        Index("ix_dup_url_hash",   "url_hash"),
        Index("ix_dup_search_job", "search_job_id"),
    )
