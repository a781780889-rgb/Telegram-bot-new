"""
URL normalisation for Telegram and WhatsApp links.

Rules enforced:
- Strip surrounding whitespace / trailing slashes
- Canonicalise domain to the primary one (t.me, chat.whatsapp.com …)
- Lower-case usernames (they are case-insensitive)
- Preserve invite-code casing (codes are case-sensitive)
- NEVER remove a code/hash that identifies a group or channel
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional

# ── Telegram patterns ──────────────────────────────────────────────────
_TG_DOMAINS = r"(?:t\.me|telegram\.me|telegram\.dog)"

# t.me/joinchat/<code>  OR  t.me/+<code>  (private invite)
_TG_INVITE_RE = re.compile(
    rf"https?://{_TG_DOMAINS}/(?:joinchat/|\+)([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)

# t.me/<username>  (public group or channel)
_TG_USER_RE = re.compile(
    rf"https?://{_TG_DOMAINS}/([A-Za-z][A-Za-z0-9_]{{3,}})",
    re.IGNORECASE,
)

# tg://  deep links – convert to https://t.me/ form
_TG_DEEP_RE = re.compile(
    r"tg://(?:join\?invite=|resolve\?domain=)([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)

# path segments that are NOT group/channel identifiers
_TG_SKIP_PATHS = frozenset(
    {"joinchat", "share", "addstickers", "addemoji", "addtheme", "bg"}
)

# ── WhatsApp patterns ──────────────────────────────────────────────────
_WA_GROUP_RE = re.compile(
    r"https?://chat\.whatsapp\.com/([A-Za-z0-9_-]{20,})",
    re.IGNORECASE,
)
_WA_CHANNEL_RE = re.compile(
    r"https?://(?:www\.)?whatsapp\.com/channel/([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)


# ══════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════

def normalize_url(raw: str) -> Optional[str]:
    """
    Return the canonical form of a Telegram or WhatsApp URL,
    or None if the URL is not a recognisable link.
    """
    url = raw.strip().rstrip("/")

    lower = url.lower()
    if any(d in lower for d in ("t.me", "telegram.me", "telegram.dog", "tg://")):
        return _norm_telegram(url)
    if any(d in lower for d in ("chat.whatsapp.com", "whatsapp.com/channel")):
        return _norm_whatsapp(url)
    return None


def get_platform(raw: str) -> Optional[str]:
    """Return 'telegram' or 'whatsapp', or None."""
    lower = raw.lower()
    if any(d in lower for d in ("t.me", "telegram.me", "telegram.dog", "tg://")):
        return "telegram"
    if any(d in lower for d in ("chat.whatsapp.com", "whatsapp.com/channel")):
        return "whatsapp"
    return None


def fingerprint(normalized: str) -> str:
    """SHA-256 hex digest used as the DB uniqueness key."""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ══════════════════════════════════════════════════════════════════
# Private helpers
# ══════════════════════════════════════════════════════════════════

def _norm_telegram(url: str) -> Optional[str]:
    # tg:// deep link → convert first
    m = _TG_DEEP_RE.match(url)
    if m:
        url = f"https://t.me/{m.group(1)}"

    # Private invite (joinchat / +code)
    m = _TG_INVITE_RE.match(url)
    if m:
        code = m.group(1)          # preserve case – codes are case-sensitive
        return f"https://t.me/joinchat/{code}"

    # Public username
    m = _TG_USER_RE.match(url)
    if m:
        name = m.group(1).lower()  # usernames are case-insensitive
        if name in _TG_SKIP_PATHS:
            return None
        return f"https://t.me/{name}"

    return None


def _norm_whatsapp(url: str) -> Optional[str]:
    m = _WA_GROUP_RE.match(url)
    if m:
        code = m.group(1)          # preserve case – invite codes are case-sensitive
        return f"https://chat.whatsapp.com/{code}"

    m = _WA_CHANNEL_RE.match(url)
    if m:
        code = m.group(1)
        return f"https://whatsapp.com/channel/{code}"

    return None
