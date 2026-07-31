"""
Search-related SQLAlchemy models.
SearchJob  - stores one search operation + its config + running counters
Link       - every unique link ever discovered (dedup enforced by DB constraint)
DuplicateLink - audit record every time a duplicate is detected
"""
from sqlalchemy import (
    Column, BigInteger, String, Boolean, DateTime,
    Integer, JSON, Text, UniqueConstraint, Index, ForeignKey,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database.database import Base


class SearchJob(Base):
    __tablename__ = "search_jobs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)

    # ── job configuration ──────────────────────────────────────────────
    account_ids   = Column(JSON, default=list)   # list[int]  DB account IDs
    platforms     = Column(String, nullable=False)  # "telegram"|"whatsapp"|"both"
    link_types    = Column(JSON, default=list)   # list[str]  e.g. ["tg_public_group"]
    search_type   = Column(String, default="normal")   # "fast"|"normal"|"deep"
    date_range    = Column(String, nullable=True)       # "today"|"week"|"month"|"year"|"custom"
    date_from     = Column(DateTime(timezone=True), nullable=True)
    date_to       = Column(DateTime(timezone=True), nullable=True)
    max_results   = Column(Integer, default=1000)

    # ── settings flags ─────────────────────────────────────────────────
    dedup_enabled  = Column(Boolean, default=True)
    compare_with_db = Column(Boolean, default=True)
    save_new       = Column(Boolean, default=True)
    ignore_invalid = Column(Boolean, default=True)

    # ── status ─────────────────────────────────────────────────────────
    status        = Column(String, default="pending", index=True)
    error_message = Column(Text, nullable=True)

    # ── timestamps ─────────────────────────────────────────────────────
    started_at   = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at   = Column(DateTime(timezone=True), onupdate=func.now())

    # ── result counters ────────────────────────────────────────────────
    found_count     = Column(Integer, default=0)
    new_count       = Column(Integer, default=0)
    duplicate_count = Column(Integer, default=0)
    invalid_count   = Column(Integer, default=0)
    tg_count        = Column(Integer, default=0)
    wa_count        = Column(Integer, default=0)

    # ── progress ───────────────────────────────────────────────────────
    sources_total   = Column(Integer, default=0)
    sources_done    = Column(Integer, default=0)
    current_source  = Column(String, nullable=True)

    # ── bot message reference for live progress editing ────────────────
    progress_chat_id    = Column(BigInteger, nullable=True)
    progress_message_id = Column(BigInteger, nullable=True)

    # ── relationships ──────────────────────────────────────────────────
    links           = relationship("Link",          back_populates="search_job", lazy="dynamic")
    duplicate_links = relationship("DuplicateLink", back_populates="search_job", lazy="dynamic")


class Link(Base):
    __tablename__ = "links"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # ── core data ──────────────────────────────────────────────────────
    platform       = Column(String, nullable=False, index=True)  # telegram|whatsapp
    link_type      = Column(String, default="unknown", index=True)
    original_url   = Column(Text, nullable=False)
    normalized_url = Column(Text, nullable=False)
    url_hash       = Column(String(64), nullable=False)  # SHA-256 of normalized_url

    # ── metadata ───────────────────────────────────────────────────────
    title          = Column(String, nullable=True)
    username       = Column(String, nullable=True, index=True)
    invite_code    = Column(String, nullable=True)
    source_context = Column(Text, nullable=True)   # snippet of msg where found

    # ── discovery tracking ─────────────────────────────────────────────
    source_account_id = Column(BigInteger, nullable=True)
    search_job_id     = Column(BigInteger, ForeignKey("search_jobs.id"), nullable=True, index=True)

    # ── status ─────────────────────────────────────────────────────────
    status     = Column(String, default="unknown")  # active|invalid|unknown
    is_deleted = Column(Boolean, default=False)

    # ── dedup timestamps ───────────────────────────────────────────────
    first_seen_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    last_seen_at  = Column(DateTime(timezone=True), server_default=func.now())
    seen_count    = Column(Integer, default=1)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # ── relationships ──────────────────────────────────────────────────
    search_job       = relationship("SearchJob", back_populates="links")
    duplicate_records = relationship("DuplicateLink", back_populates="existing_link")

    __table_args__ = (
        # CRITICAL: prevents duplicate inserts even under concurrent load
        UniqueConstraint("platform", "url_hash", name="uq_link_platform_hash"),
        Index("ix_link_platform_hash", "platform", "url_hash"),
        Index("ix_link_type_platform", "link_type", "platform"),
        Index("ix_link_first_seen", "first_seen_at"),
    )


class DuplicateLink(Base):
    """Records every occurrence of a link that already exists in `links`."""
    __tablename__ = "duplicate_links"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    original_url   = Column(Text, nullable=False)
    normalized_url = Column(Text, nullable=False)
    url_hash       = Column(String(64), nullable=False)
    platform       = Column(String, nullable=False)

    search_job_id      = Column(BigInteger, ForeignKey("search_jobs.id"), nullable=True, index=True)
    existing_link_id   = Column(BigInteger, ForeignKey("links.id"),       nullable=True)
    source_account_id  = Column(BigInteger, nullable=True)

    detected_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # ── relationships ──────────────────────────────────────────────────
    search_job    = relationship("SearchJob", back_populates="duplicate_links")
    existing_link = relationship("Link",       back_populates="duplicate_records")

    __table_args__ = (
        Index("ix_dup_url_hash",    "url_hash"),
        Index("ix_dup_search_job",  "search_job_id"),
    )
