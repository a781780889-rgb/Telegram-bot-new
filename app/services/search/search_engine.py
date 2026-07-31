"""
Telethon-based search engine.

Strategy:
- Pre-configured source channel usernames are searched for messages
  that contain Telegram / WhatsApp invite links.
- client.iter_messages(entity, search=keyword) is the only Telegram
  API call used – fully read-only, no joins, no sends.
- Multiple accounts rotate across sources to spread load.
- Respects FloodWait with a bounded sleep; does NOT try to bypass it.

Search depth controls:
  fast   – 3 sources, 100 messages / source, 1 keyword
  normal – 12 sources, 500 messages / source, 3 keywords
  deep   – 25 sources, 2 000 messages / source, 6 keywords
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import AsyncGenerator, List, Optional, Tuple

from loguru import logger
from telethon import TelegramClient
from telethon.errors import (
    ChannelPrivateError,
    ChatAdminRequiredError,
    FloodWaitError,
    RPCError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from telethon.tl.types import Message

from app.services.search.link_extractor import extract_by_platforms

# ── Source channels (public directories that share group links) ────────
# These are example usernames; substitute with real active channels
# once the system is in production. The engine silently skips any
# channel that is unavailable or returns no results.
_SOURCES_FAST = [
    "tggroups",
    "wa_links_ar",
    "linkstelegram",
]
_SOURCES_NORMAL = _SOURCES_FAST + [
    "telegram_groups_ar",
    "whatsapp_groups_ar",
    "tg_public_groups",
    "wa_channel_links",
    "arab_groups_links",
    "groups_directory",
    "link_exchange_ar",
    "channel_directory",
    "open_groups",
    "groups_sharing",
]
_SOURCES_DEEP = _SOURCES_NORMAL + [
    "واتساب_مجموعات",
    "روابط_مجاميع",
    "مجموعات_عامة",
    "تبادل_روابط",
    "link_sharing_hub",
    "tglinks_public",
    "wa_invite_links",
    "groups_hub",
    "telegram_channels_list",
    "public_channels_ar",
    "group_links_collection",
    "wa_groups_open",
    "tme_invite_links",
]

# keywords searched inside each source channel
_KW_TG = ["t.me", "joinchat", "telegram.me"]
_KW_WA = ["chat.whatsapp.com", "whatsapp.com/channel"]
_KW_ALL = _KW_TG + _KW_WA

_MSGS_PER_SOURCE = {"fast": 100, "normal": 500, "deep": 2000}
_KW_COUNT        = {"fast": 1,   "normal": 3,   "deep": 6}
_MAX_FLOOD_SLEEP = 60   # never sleep more than 60 s for a single FloodWait


class SearchEngine:
    """
    Yields (raw_url, source_name, context_snippet) tuples.
    The caller owns validation / deduplication / persistence.
    """

    def __init__(
        self,
        clients: List[TelegramClient],
        platforms: str,               # "telegram"|"whatsapp"|"both"
        search_type: str = "normal",
        date_from: Optional[datetime] = None,
        date_to:   Optional[datetime] = None,
        max_results: int = 1000,
        stop_event:  Optional[asyncio.Event] = None,
        pause_event: Optional[asyncio.Event] = None,
    ):
        if not clients:
            raise ValueError("SearchEngine requires at least one connected client")

        self.clients     = clients
        self.platforms   = platforms
        self.search_type = search_type
        self.date_from   = date_from
        self.date_to     = date_to
        self.max_results = max_results or 99_999_999

        self.stop_event  = stop_event  or asyncio.Event()
        self.pause_event = pause_event or asyncio.Event()
        self.pause_event.set()   # running by default

        self._platforms_list = (
            ["telegram", "whatsapp"] if platforms == "both" else [platforms]
        )
        self._sources     = self._choose_sources()
        self._msg_limit   = _MSGS_PER_SOURCE.get(search_type, 500)
        self._kw_count    = _KW_COUNT.get(search_type, 3)

    # ── source + keyword selection ─────────────────────────────────────
    def _choose_sources(self) -> List[str]:
        if self.search_type == "fast":
            return _SOURCES_FAST
        if self.search_type == "deep":
            return _SOURCES_DEEP
        return _SOURCES_NORMAL

    def _keywords(self) -> List[str]:
        if self.platforms == "telegram":
            base = _KW_TG
        elif self.platforms == "whatsapp":
            base = _KW_WA
        else:
            base = _KW_ALL
        return base[: self._kw_count]

    # ── main generator ─────────────────────────────────────────────────
    async def search(self) -> AsyncGenerator[Tuple[str, str, str], None]:
        """Yields (raw_url, source, context)."""
        found      = 0
        client_idx = 0
        keywords   = self._keywords()

        for source in self._sources:
            if self.stop_event.is_set():
                return
            await self._wait_resume()

            if found >= self.max_results:
                return

            client = self.clients[client_idx % len(self.clients)]
            client_idx += 1

            logger.debug(f"[search] source={source!r}")

            async for raw_url, context in self._scan_source(client, source, keywords):
                if self.stop_event.is_set():
                    return
                await self._wait_resume()

                yield raw_url, source, context
                found += 1
                if found >= self.max_results:
                    return

    # ── per-source scanner ─────────────────────────────────────────────
    async def _scan_source(
        self,
        client: TelegramClient,
        source: str,
        keywords: List[str],
    ) -> AsyncGenerator[Tuple[str, str], None]:
        """Yields (raw_url, context_snippet) from one source channel."""

        # Resolve the entity once
        try:
            entity = await client.get_entity(source)
        except (UsernameNotOccupiedError, UsernameInvalidError, ValueError):
            logger.debug(f"[search] source not found: {source!r}")
            return
        except ChannelPrivateError:
            logger.debug(f"[search] source is private: {source!r}")
            return
        except FloodWaitError as e:
            secs = min(e.seconds, _MAX_FLOOD_SLEEP)
            logger.warning(f"[search] FloodWait {e.seconds}s on get_entity({source}), sleeping {secs}s")
            await asyncio.sleep(secs)
            return
        except Exception as e:
            logger.debug(f"[search] get_entity({source}) error: {e}")
            return

        seen_in_source: set[str] = set()

        for keyword in keywords:
            if self.stop_event.is_set():
                return

            try:
                async for msg in client.iter_messages(
                    entity,
                    limit=self._msg_limit,
                    search=keyword,
                    offset_date=self.date_to,
                ):
                    if not isinstance(msg, Message):
                        continue

                    # date_from filter
                    if self.date_from and msg.date:
                        msg_ts = msg.date.replace(tzinfo=None)
                        df     = self.date_from.replace(tzinfo=None)
                        if msg_ts < df:
                            continue

                    text = msg.text or msg.caption or ""
                    if not text:
                        continue

                    for raw_url in extract_by_platforms(text, self._platforms_list):
                        if raw_url not in seen_in_source:
                            seen_in_source.add(raw_url)
                            yield raw_url, text[:300]

                # be polite between keywords
                await asyncio.sleep(0.5)

            except FloodWaitError as e:
                secs = min(e.seconds, _MAX_FLOOD_SLEEP)
                logger.warning(f"[search] FloodWait {e.seconds}s in {source}/{keyword}, sleeping {secs}s")
                await asyncio.sleep(secs)
            except (ChatAdminRequiredError, ChannelPrivateError):
                logger.debug(f"[search] no read access in {source}")
                return
            except RPCError as e:
                logger.debug(f"[search] RPCError in {source}: {e}")
            except Exception as e:
                logger.debug(f"[search] unexpected error in {source}: {e}")

    # ── helpers ────────────────────────────────────────────────────────
    async def _wait_resume(self) -> None:
        while not self.pause_event.is_set():
            await asyncio.sleep(0.5)
