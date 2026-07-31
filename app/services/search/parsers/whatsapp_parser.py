"""
WhatsAppParser — discovers WhatsApp group/channel links from publicly
available web sources using aiohttp.

Rules (hard limits):
  • Never attempt to join groups automatically.
  • Never bypass CAPTCHA or rate-limit systems.
  • Only read publicly accessible pages.
  • Respect robots.txt implicitly by targeting safe endpoints.
  • Limited retries with bounded backoff — no infinite loops.
"""

from __future__ import annotations

import asyncio
import re
from typing import AsyncGenerator, List

import aiohttp
from loguru import logger

from app.services.search.normalizer import NormalizedLink, normalize, extract_links_from_text

# ── public sources of WhatsApp links ─────────────────────────────────────
# These are pages that aggregate publicly shared WhatsApp join links.

_FAST_SOURCES: List[str] = [
    "https://groupsor.link/wp-json/wp/v2/posts?per_page=20&orderby=date",
    "https://www.whatsapp-group-links.com/latest-links/",
]

_NORMAL_EXTRAS: List[str] = [
    "https://groupsor.link/?page=2",
    "https://groupsor.link/?page=3",
    "https://chat.whatsapp.group/",
    "https://www.whatsapp-group-links.com/whatsapp-group-links/",
]

_DEEP_EXTRAS: List[str] = [
    "https://groupsor.link/?page=4",
    "https://groupsor.link/?page=5",
    "https://whatsapplinks.xyz/",
    "https://www.whatsapp-group-links.com/page/2/",
    "https://www.whatsapp-group-links.com/page/3/",
]


def _sources_for_depth(depth: str) -> List[str]:
    if depth == "fast":
        return _FAST_SOURCES
    if depth == "deep":
        return _FAST_SOURCES + _NORMAL_EXTRAS + _DEEP_EXTRAS
    return _FAST_SOURCES + _NORMAL_EXTRAS


# ── WhatsApp link regex ───────────────────────────────────────────────────

_WA_LINK_RE = re.compile(
    r"https?://(?:"
    r"chat\.whatsapp\.com/[A-Za-z0-9]{20,}"
    r"|whatsapp\.com/channel/[A-Za-z0-9_-]{20,}"
    r")",
    re.IGNORECASE,
)

# ── timeout / retry config ────────────────────────────────────────────────

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)
_MAX_RETRIES = 2
_RETRY_DELAY = 3.0

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; LinkBot/1.0; "
        "+https://github.com/example/linkbot)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "ar,en;q=0.5",
}


# ── public entry point ────────────────────────────────────────────────────

async def search_whatsapp_links(
    depth: str = "normal",
    link_types_config: dict | None = None,
    *,
    stop_event: asyncio.Event | None = None,
    pause_event: asyncio.Event | None = None,
) -> AsyncGenerator[NormalizedLink, None]:
    """
    Async generator that yields NormalizedLink objects for WhatsApp
    groups and channels found in public web sources.
    """
    cfg = link_types_config or {}
    want_groups   = cfg.get("wa_groups",   True)
    want_channels = cfg.get("wa_channels", True)

    sources = _sources_for_depth(depth)

    async with aiohttp.ClientSession(
        timeout=_REQUEST_TIMEOUT, headers=_HEADERS
    ) as session:
        for url in sources:
            if stop_event and stop_event.is_set():
                break
            if pause_event:
                await pause_event.wait()

            html = await _fetch_safe(session, url)
            if not html:
                continue

            for raw_link in _WA_LINK_RE.findall(html):
                normed = normalize(raw_link)
                if normed is None:
                    continue

                # Apply type filters
                if normed.link_type == "wa_group" and not want_groups:
                    continue
                if normed.link_type == "wa_channel" and not want_channels:
                    continue

                yield normed

            await asyncio.sleep(2.0)  # polite delay between sources


# ── http helper ───────────────────────────────────────────────────────────

async def _fetch_safe(session: aiohttp.ClientSession, url: str) -> str | None:
    """Fetch a URL, return the response text or None on any error."""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status == 200:
                    return await resp.text(errors="replace")
                if resp.status in (429, 503):
                    # Rate limited — wait and retry
                    logger.warning(f"HTTP {resp.status} from {url}, waiting {_RETRY_DELAY}s")
                    await asyncio.sleep(_RETRY_DELAY * attempt)
                    continue
                logger.info(f"HTTP {resp.status} from {url} — skipping")
                return None
        except aiohttp.ClientError as exc:
            logger.warning(f"Fetch attempt {attempt} failed for {url}: {exc}")
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_DELAY)
        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching {url}")
            return None
        except Exception as exc:
            logger.error(f"Unexpected error fetching {url}: {exc}")
            return None
    return None
