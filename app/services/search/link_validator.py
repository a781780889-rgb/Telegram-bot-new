"""
Validate raw URLs and classify them into platform + link_type.

Without making live API calls we can only approximate the type for
Telegram username-based links (group vs channel); we default to
'tg_public_group'. The caller may refine this later if needed.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

from app.services.search.url_normalizer import (
    get_platform,
    normalize_url,
)

# ── classification regexes (operate on already-normalised URLs) ────────
_TG_INVITE_RE  = re.compile(r"^https://t\.me/joinchat/[A-Za-z0-9_-]+$")
_TG_USER_RE    = re.compile(r"^https://t\.me/[A-Za-z][A-Za-z0-9_]{3,}$")
_WA_GROUP_RE   = re.compile(r"^https://chat\.whatsapp\.com/[A-Za-z0-9_-]+$")
_WA_CHANNEL_RE = re.compile(r"^https://whatsapp\.com/channel/[A-Za-z0-9_-]+$")


def classify_telegram(normalised: str) -> str:
    """
    Returns one of: tg_private_group | tg_public_group | unknown
    Note: tg_public_group is used for both public groups and channels
    since the distinction requires an API lookup.
    """
    if _TG_INVITE_RE.match(normalised):
        return "tg_private_group"
    if _TG_USER_RE.match(normalised):
        return "tg_public_group"
    return "unknown"


def classify_whatsapp(normalised: str) -> str:
    if _WA_GROUP_RE.match(normalised):
        return "wa_group"
    if _WA_CHANNEL_RE.match(normalised):
        return "wa_channel"
    return "unknown"


def validate_and_classify(
    raw: str,
) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
    """
    Returns (is_valid, platform, link_type, normalised_url).

    Example:
    >>> validate_and_classify("https://chat.whatsapp.com/ABC1234567890XXXXX")
    (True, "whatsapp", "wa_group", "https://chat.whatsapp.com/ABC1234567890XXXXX")
    """
    platform = get_platform(raw)
    if platform is None:
        return False, None, None, None

    normalised = normalize_url(raw)
    if normalised is None:
        return False, platform, None, None

    if platform == "telegram":
        link_type = classify_telegram(normalised)
    else:
        link_type = classify_whatsapp(normalised)

    return True, platform, link_type, normalised
