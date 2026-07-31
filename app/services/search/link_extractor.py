"""
Regex-based link extraction from raw text.
Returns raw URL strings; normalization / validation happens downstream.
"""
from __future__ import annotations

import re
from typing import List

# ── Telegram ──────────────────────────────────────────────────────────
_TG_PATTERNS = [
    # private invite:  t.me/joinchat/CODE  or  t.me/+CODE
    r"https?://(?:t\.me|telegram\.me|telegram\.dog)/(?:joinchat/|\+)[A-Za-z0-9_-]+",
    # public:          t.me/username
    r"https?://(?:t\.me|telegram\.me|telegram\.dog)/[A-Za-z][A-Za-z0-9_]{3,}",
    # tg:// deep links
    r"tg://(?:join\?invite=|resolve\?domain=)[A-Za-z0-9_-]+",
]

# ── WhatsApp ──────────────────────────────────────────────────────────
_WA_PATTERNS = [
    # group invite
    r"https?://chat\.whatsapp\.com/[A-Za-z0-9_-]{20,}",
    # channel
    r"https?://(?:www\.)?whatsapp\.com/channel/[A-Za-z0-9_-]+",
]

_TG_RE  = re.compile("|".join(_TG_PATTERNS), re.IGNORECASE)
_WA_RE  = re.compile("|".join(_WA_PATTERNS), re.IGNORECASE)
_ALL_RE = re.compile("|".join(_TG_PATTERNS + _WA_PATTERNS), re.IGNORECASE)


def extract_telegram_links(text: str) -> List[str]:
    return _TG_RE.findall(text) if text else []


def extract_whatsapp_links(text: str) -> List[str]:
    return _WA_RE.findall(text) if text else []


def extract_all_links(text: str) -> List[str]:
    return _ALL_RE.findall(text) if text else []


def extract_by_platforms(text: str, platforms: List[str]) -> List[str]:
    """
    Extract links for the requested platforms.
    platforms: list containing 'telegram' and/or 'whatsapp'
    """
    if not text:
        return []
    result: List[str] = []
    if "telegram" in platforms:
        result.extend(extract_telegram_links(text))
    if "whatsapp" in platforms:
        result.extend(extract_whatsapp_links(text))
    return result
