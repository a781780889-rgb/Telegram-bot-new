"""
TelegramParser — discovers Telegram group/channel links via Telethon.

Strategy by depth
─────────────────
FAST   → search 5 broad terms, ~50 results each  → ≈250 raw hits
NORMAL → search 15 terms, browse existing dialogs → ≈1 000 raw hits
DEEP   → search 30 terms + extended dialog scan   → ≈3 000+ raw hits

All searches use the public Telegram API only — no scraping,
no CAPTCHA bypasses, no banned methods.  FloodWaitError is handled
with a bounded sleep; the parser never retries indefinitely.
"""

from __future__ import annotations

import asyncio
import os
from typing import AsyncGenerator, List

from loguru import logger
from telethon import TelegramClient, errors
from telethon.tl import functions, types as tl_types

from app.config.config import settings
from app.services.search.normalizer import NormalizedLink, normalize

SESSIONS_DIR = "sessions"
MAX_FLOOD_WAIT = 60   # seconds — skip a query rather than wait longer

# ── query banks ──────────────────────────────────────────────────────────

_FAST_QUERIES: List[str] = [
    "group", "channel", "community", "news", "chat",
]

_NORMAL_EXTRAS: List[str] = [
    "مجموعة", "قناة", "أخبار", "تواصل", "عربي",
    "team", "official", "support", "public", "tech",
]

_DEEP_EXTRAS: List[str] = [
    "بيع", "شراء", "وظائف", "عقارات", "استثمار",
    "crypto", "forex", "trading", "market", "business",
    "رياضة", "ترفيه", "ثقافة", "تعليم", "صحة",
    "fashion", "food", "travel", "gaming", "music",
    "برمجة", "تقنية", "ذكاء اصطناعي",
    "politics", "science", "sports",
]

_NORMAL_QUERIES = _FAST_QUERIES + _NORMAL_EXTRAS
_DEEP_QUERIES   = _NORMAL_QUERIES + _DEEP_EXTRAS


def _queries_for_depth(depth: str) -> List[str]:
    if depth == "fast":
        return _FAST_QUERIES
    if depth == "deep":
        return _DEEP_QUERIES
    return _NORMAL_QUERIES


# ── session loader ────────────────────────────────────────────────────────

def _session_path(session_name: str) -> str:
    return os.path.join(SESSIONS_DIR, session_name)


async def _get_client(session_name: str) -> TelegramClient | None:
    path = _session_path(session_name)
    if not os.path.exists(f"{path}.session"):
        logger.warning(f"Session file not found: {path}.session")
        return None
    client = TelegramClient(path, settings.API_ID, settings.API_HASH)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            logger.warning(f"Session {session_name} not authorized")
            await client.disconnect()
            return None
    except Exception as exc:
        logger.error(f"Failed to connect session {session_name}: {exc}")
        try:
            await client.disconnect()
        except Exception:
            pass
        return None
    return client


# ── core discovery ────────────────────────────────────────────────────────

async def search_via_session(
    session_name: str,
    depth: str = "normal",
    link_types_config: dict | None = None,
    *,
    stop_event: asyncio.Event | None = None,
    pause_event: asyncio.Event | None = None,
) -> AsyncGenerator[NormalizedLink, None]:
    """
    Async generator.  Yields NormalizedLink objects discovered via the
    given Telethon session.  The caller is responsible for duplicate
    checking and DB persistence.
    """
    cfg = link_types_config or {}
    want_groups  = cfg.get("tg_groups",   True)
    want_channels = cfg.get("tg_channels", True)
    want_private  = cfg.get("tg_private",  True)

    client = await _get_client(session_name)
    if client is None:
        return

    try:
        queries = _queries_for_depth(depth)

        # ── Phase 1: Global search by query ───────────────────────────
        for query in queries:
            if stop_event and stop_event.is_set():
                break
            if pause_event:
                await pause_event.wait()  # blocks while paused

            try:
                result = await client(
                    functions.contacts.SearchRequest(q=query, limit=50)
                )
                async for link in _extract_from_search_result(result, want_groups, want_channels, want_private):
                    yield link
            except errors.FloodWaitError as exc:
                secs = min(exc.seconds, MAX_FLOOD_WAIT)
                logger.warning(f"FloodWait {exc.seconds}s on query='{query}', sleeping {secs}s")
                await asyncio.sleep(secs)
            except Exception as exc:
                logger.warning(f"Search query '{query}' error: {exc}")

            await asyncio.sleep(1.5)  # gentle rate limit between queries

        # ── Phase 2 (normal+deep): browse existing joined dialogs ──────
        if depth in ("normal", "deep"):
            if stop_event and stop_event.is_set():
                return
            async for link in _extract_from_dialogs(client, want_groups, want_channels, stop_event, pause_event):
                yield link

    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def _extract_from_search_result(
    result,
    want_groups: bool,
    want_channels: bool,
    want_private: bool,
) -> AsyncGenerator[NormalizedLink, None]:
    chats = getattr(result, "chats", []) or []
    for chat in chats:
        link_str = _chat_to_url(chat, want_groups, want_channels, want_private)
        if link_str is None:
            continue
        normed = normalize(link_str)
        if normed is not None:
            # Upgrade link_type based on Telethon entity type
            upgraded = _upgrade_link_type(normed, chat)
            yield upgraded


async def _extract_from_dialogs(
    client: TelegramClient,
    want_groups: bool,
    want_channels: bool,
    stop_event: asyncio.Event | None,
    pause_event: asyncio.Event | None,
) -> AsyncGenerator[NormalizedLink, None]:
    try:
        async for dialog in client.iter_dialogs(limit=500):
            if stop_event and stop_event.is_set():
                break
            if pause_event:
                await pause_event.wait()

            entity = dialog.entity
            link_str = _chat_to_url(entity, want_groups, want_channels, want_private=True)
            if link_str is None:
                continue
            normed = normalize(link_str)
            if normed is not None:
                yield _upgrade_link_type(normed, entity)
    except Exception as exc:
        logger.warning(f"iter_dialogs error: {exc}")


def _chat_to_url(chat, want_groups: bool, want_channels: bool, want_private: bool) -> str | None:
    """Convert a Telethon chat entity to a join URL string, or None if filtered out."""
    is_channel   = isinstance(chat, (tl_types.Channel, tl_types.ChannelForbidden))
    is_group     = isinstance(chat, (tl_types.Chat, tl_types.ChatForbidden))
    is_megagroup = is_channel and getattr(chat, "megagroup", False)

    # Apply type filters
    if is_group or is_megagroup:
        if not want_groups:
            return None
    elif is_channel and not is_megagroup:
        if not want_channels:
            return None

    username = getattr(chat, "username", None)
    if username:
        return f"https://t.me/{username}"

    # Private invite link
    if not want_private:
        return None
    invite_link = getattr(chat, "invite_link", None)
    if invite_link:
        return invite_link

    return None


def _upgrade_link_type(link: NormalizedLink, entity) -> NormalizedLink:
    """
    Replace the generic "public_group" link_type with the real type
    derived from the Telethon entity.
    """
    from dataclasses import replace

    is_megagroup = getattr(entity, "megagroup", False)
    is_channel   = isinstance(entity, (tl_types.Channel, tl_types.ChannelForbidden))

    if link.link_type == "private_group":
        return link

    if is_channel:
        new_type = "public_group" if is_megagroup else "channel"
        return replace(link, link_type=new_type)

    return link
