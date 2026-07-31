"""
URL Normalizer for Telegram and WhatsApp links.

Design rules
────────────
• Never strip a path segment that carries group/channel identity.
• Only remove parameters/fragments that are provably tracking noise.
• Use SHA-256 of the normalized URL as the fingerprint (url_hash).
• Return LinkPlatform + LinkType alongside the cleaned URL so callers
  do not have to re-parse.

Supported patterns
──────────────────
Telegram:
  https://t.me/username              → public_group or channel (resolved later)
  https://t.me/+INVITE_HASH          → private_group
  https://t.me/joinchat/INVITE_HASH  → private_group (legacy format)
  https://telegram.me/username       → same as t.me

WhatsApp:
  https://chat.whatsapp.com/INVITE_CODE  → wa_group
  https://whatsapp.com/channel/CODE      → wa_channel
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode


# ── regex patterns ───────────────────────────────────────────────────────

# Telegram username (1–32 chars, letters/digits/underscores, starts with letter or digit)
_TG_USERNAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_]{0,31}$")

# t.me / telegram.me domains
_TG_DOMAINS = {"t.me", "telegram.me", "www.t.me", "www.telegram.me"}

# WhatsApp domains
_WA_GROUP_DOMAIN   = "chat.whatsapp.com"
_WA_CHANNEL_DOMAIN = "whatsapp.com"
_WA_CHANNEL_PATH   = "/channel/"


@dataclass(frozen=True)
class NormalizedLink:
    original_url:   str
    normalized_url: str
    url_hash:       str     # SHA-256 hex of normalized_url
    platform:       str     # "telegram" | "whatsapp"
    link_type:      str     # "public_group" | "private_group" | "channel" | "wa_group" | "wa_channel" | "unknown"
    username:       Optional[str] = None
    invite_code:    Optional[str] = None


def normalize(raw_url: str) -> Optional[NormalizedLink]:
    """
    Normalize a raw URL string.  Returns None if the URL cannot be
    recognized as a valid Telegram or WhatsApp link.
    """
    url = _clean_raw(raw_url)
    if not url:
        return None

    parsed = urlparse(url)
    host   = parsed.netloc.lower().lstrip("www.")

    if host in _TG_DOMAINS or host in {"t.me", "telegram.me"}:
        return _normalize_telegram(url, parsed)

    if host == _WA_GROUP_DOMAIN or (host == _WA_CHANNEL_DOMAIN and parsed.path.startswith(_WA_CHANNEL_PATH)):
        return _normalize_whatsapp(url, parsed, host)

    return None


# ── Telegram ─────────────────────────────────────────────────────────────

def _normalize_telegram(url: str, parsed) -> Optional[NormalizedLink]:
    path = parsed.path.strip("/")

    # Legacy private: /joinchat/HASH
    if path.startswith("joinchat/"):
        invite = path[len("joinchat/"):]
        if not invite:
            return None
        normed = f"https://t.me/joinchat/{invite}"
        return NormalizedLink(
            original_url=url,
            normalized_url=normed,
            url_hash=_sha256(normed),
            platform="telegram",
            link_type="private_group",
            invite_code=invite,
        )

    # Modern private: /+HASH
    if path.startswith("+"):
        invite = path[1:]
        if not invite:
            return None
        normed = f"https://t.me/+{invite}"
        return NormalizedLink(
            original_url=url,
            normalized_url=normed,
            url_hash=_sha256(normed),
            platform="telegram",
            link_type="private_group",
            invite_code=invite,
        )

    # Public username (may include /s/ prefix for preview)
    username = path.split("/")[0].lstrip("@")
    if not username or not _TG_USERNAME_RE.match(username):
        return None

    normed = f"https://t.me/{username.lower()}"
    # We can't tell group vs channel without a live API call, so mark unknown.
    # The parser layer upgrades this based on Telethon metadata.
    link_type = "public_group"

    return NormalizedLink(
        original_url=url,
        normalized_url=normed,
        url_hash=_sha256(normed),
        platform="telegram",
        link_type=link_type,
        username=username.lower(),
    )


# ── WhatsApp ─────────────────────────────────────────────────────────────

def _normalize_whatsapp(url: str, parsed, host: str) -> Optional[NormalizedLink]:
    path = parsed.path.strip("/")

    if host == _WA_GROUP_DOMAIN:
        # https://chat.whatsapp.com/INVITE_CODE
        code = path.split("/")[0]
        if not code:
            return None
        normed = f"https://chat.whatsapp.com/{code}"
        return NormalizedLink(
            original_url=url,
            normalized_url=normed,
            url_hash=_sha256(normed),
            platform="whatsapp",
            link_type="wa_group",
            invite_code=code,
        )

    if host == _WA_CHANNEL_DOMAIN and parsed.path.startswith(_WA_CHANNEL_PATH):
        code = parsed.path[len(_WA_CHANNEL_PATH):].strip("/").split("/")[0]
        if not code:
            return None
        normed = f"https://whatsapp.com/channel/{code}"
        return NormalizedLink(
            original_url=url,
            normalized_url=normed,
            url_hash=_sha256(normed),
            platform="whatsapp",
            link_type="wa_channel",
            invite_code=code,
        )

    return None


# ── helpers ──────────────────────────────────────────────────────────────

def _clean_raw(raw: str) -> str:
    """Strip whitespace, quotes, trailing punctuation and normalise scheme."""
    url = raw.strip().strip("'\"").rstrip(".,:;!?)")
    if not url:
        return ""
    url = re.sub(r"\s+", "", url)   # remove internal spaces (copy-paste artefacts)
    if url.startswith("tg://"):
        return ""                   # deep links — not a joinable URL
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.replace("http://", "https://")  # force HTTPS


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ── link extraction from raw text ─────────────────────────────────────────

# Matches anything that looks like a t.me, telegram.me, chat.whatsapp.com,
# or whatsapp.com/channel link inside a body of text.
_LINK_EXTRACT_RE = re.compile(
    r"https?://(?:www\.)?(?:"
    r"t\.me|telegram\.me|"
    r"chat\.whatsapp\.com|"
    r"whatsapp\.com/channel"
    r")[^\s\"'<>\]\)]*",
    re.IGNORECASE,
)


def extract_links_from_text(text: str) -> list[str]:
    """Return all raw URL strings that look like TG/WA links."""
    return _LINK_EXTRACT_RE.findall(text)
