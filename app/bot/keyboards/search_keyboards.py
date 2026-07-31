"""
Search wizard keyboards.

Callback-data scheme (kept under 64 bytes each):
  s:ac:t:{id}   toggle account id
  s:ac:all      select all accounts
  s:ac:nn       deselect all
  s:ac:nx       proceed from accounts step
  s:pl:{val}    select platform (tg/wa/bo)
  s:pl:nx       proceed from platform
  s:lt:t:{key}  toggle link-type checkbox
  s:lt:nx       proceed from link-types
  s:dp:{val}    select depth (fa/no/de)
  s:dp:nx       proceed from depth
  s:pd:{val}    select period (dy/wk/mn/yr/cu)
  s:pd:nx       proceed from period
  s:cf          confirm and start
  s:cx          cancel wizard
  s:ps:{id}     pause running job
  s:rs:{id}     resume paused job
  s:st:{id}     stop job
  s:ex:tg:{id}  export Telegram links
  s:ex:wa:{id}  export WhatsApp links
  s:ex:al:{id}  export all links
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


# ──────────────────────────────────────────────────────────────────────────
# Step 1 — Account selection
# ──────────────────────────────────────────────────────────────────────────

def accounts_keyboard(
    accounts: list,          # List[Account]
    selected_ids: Set[int],
) -> InlineKeyboardMarkup:
    rows = []
    for acc in accounts:
        tick   = "✅" if acc.id in selected_ids else "☐"
        status = "🟢" if acc.is_connected else "🔴"
        label  = f"{tick} {status} {acc.phone or acc.session_name}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"s:ac:t:{acc.id}")])

    rows.append([
        InlineKeyboardButton(text="✔️ تحديد الكل",      callback_data="s:ac:all"),
        InlineKeyboardButton(text="✘ إلغاء الكل",       callback_data="s:ac:nn"),
    ])
    rows.append([
        InlineKeyboardButton(text="❌ إلغاء",            callback_data="s:cx"),
        InlineKeyboardButton(text="التالي ➡️",           callback_data="s:ac:nx"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ──────────────────────────────────────────────────────────────────────────
# Step 2 — Platform
# ──────────────────────────────────────────────────────────────────────────

_PLATFORMS = [
    ("tg",  "📱 Telegram فقط"),
    ("wa",  "💬 WhatsApp فقط"),
    ("bo",  "📱💬 Telegram + WhatsApp"),
]


def platform_keyboard(selected: str) -> InlineKeyboardMarkup:
    rows = []
    for val, label in _PLATFORMS:
        tick = "🔘" if selected == val else "⚪"
        rows.append([InlineKeyboardButton(text=f"{tick} {label}", callback_data=f"s:pl:{val}")])

    rows.append([
        InlineKeyboardButton(text="⬅️ رجوع",  callback_data="s:bk:1"),
        InlineKeyboardButton(text="التالي ➡️", callback_data="s:pl:nx"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ──────────────────────────────────────────────────────────────────────────
# Step 3 — Link types
# ──────────────────────────────────────────────────────────────────────────

_TG_LINK_TYPES = [
    ("tg_groups",   "👥 مجموعات Telegram العامة"),
    ("tg_channels", "📢 قنوات Telegram"),
    ("tg_private",  "🔒 مجموعات Telegram الخاصة"),
]

_WA_LINK_TYPES = [
    ("wa_groups",   "👥 مجموعات WhatsApp"),
    ("wa_channels", "📢 قنوات WhatsApp"),
]


def link_types_keyboard(
    platform: str,           # "tg" | "wa" | "bo"
    selected: Dict[str, bool],
) -> InlineKeyboardMarkup:
    rows = []

    types_to_show = []
    if platform in ("tg", "bo"):
        types_to_show.extend(_TG_LINK_TYPES)
    if platform in ("wa", "bo"):
        types_to_show.extend(_WA_LINK_TYPES)

    for key, label in types_to_show:
        tick = "✅" if selected.get(key, True) else "☐"
        rows.append([InlineKeyboardButton(text=f"{tick} {label}", callback_data=f"s:lt:t:{key}")])

    rows.append([
        InlineKeyboardButton(text="⬅️ رجوع",  callback_data="s:bk:2"),
        InlineKeyboardButton(text="التالي ➡️", callback_data="s:lt:nx"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ──────────────────────────────────────────────────────────────────────────
# Step 4 — Depth
# ──────────────────────────────────────────────────────────────────────────

_DEPTHS = [
    ("fa", "⚡ بحث سريع    — نطاق أقل، سرعة أعلى"),
    ("no", "🔎 بحث عادي   — توازن بين السرعة والشمول"),
    ("de", "🧠 بحث عميق   — أوسع نطاقاً، يستغرق وقتاً أطول"),
]


def depth_keyboard(selected: str) -> InlineKeyboardMarkup:
    rows = []
    for val, label in _DEPTHS:
        tick = "🔘" if selected == val else "⚪"
        rows.append([InlineKeyboardButton(text=f"{tick} {label}", callback_data=f"s:dp:{val}")])

    rows.append([
        InlineKeyboardButton(text="⬅️ رجوع",  callback_data="s:bk:3"),
        InlineKeyboardButton(text="التالي ➡️", callback_data="s:dp:nx"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ──────────────────────────────────────────────────────────────────────────
# Step 5 — Time period
# ──────────────────────────────────────────────────────────────────────────

_PERIODS = [
    ("dy", "📅 آخر يوم"),
    ("wk", "📅 آخر أسبوع"),
    ("mn", "📅 آخر شهر"),
    ("yr", "📅 آخر سنة"),
    ("cu", "📅 تحديد تاريخ يدوي"),
]


def period_keyboard(selected: str) -> InlineKeyboardMarkup:
    rows = []
    for val, label in _PERIODS:
        tick = "🔘" if selected == val else "⚪"
        rows.append([InlineKeyboardButton(text=f"{tick} {label}", callback_data=f"s:pd:{val}")])

    rows.append([
        InlineKeyboardButton(text="⬅️ رجوع",  callback_data="s:bk:4"),
        InlineKeyboardButton(text="التالي ➡️", callback_data="s:pd:nx"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ──────────────────────────────────────────────────────────────────────────
# Step 6 — Confirmation
# ──────────────────────────────────────────────────────────────────────────

def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⬅️ رجوع",       callback_data="s:bk:5"),
            InlineKeyboardButton(text="🚀 بدء البحث",   callback_data="s:cf"),
        ],
        [InlineKeyboardButton(text="❌ إلغاء",           callback_data="s:cx")],
    ])


# ──────────────────────────────────────────────────────────────────────────
# Running controls
# ──────────────────────────────────────────────────────────────────────────

def running_keyboard(job_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⏸️ إيقاف مؤقت", callback_data=f"s:ps:{job_id}"),
            InlineKeyboardButton(text="⏹️ إيقاف",       callback_data=f"s:st:{job_id}"),
        ],
    ])


def paused_keyboard(job_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="▶️ استمرار",  callback_data=f"s:rs:{job_id}"),
            InlineKeyboardButton(text="⏹️ إيقاف",    callback_data=f"s:st:{job_id}"),
        ],
    ])


# ──────────────────────────────────────────────────────────────────────────
# Results / export
# ──────────────────────────────────────────────────────────────────────────

def results_keyboard(job_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📥 روابط Telegram", callback_data=f"s:ex:tg:{job_id}"),
            InlineKeyboardButton(text="📥 روابط WhatsApp",  callback_data=f"s:ex:wa:{job_id}"),
        ],
        [InlineKeyboardButton(text="📥 تحميل الكل (CSV)",   callback_data=f"s:ex:al:{job_id}")],
        [InlineKeyboardButton(text="🏠 القائمة الرئيسية",    callback_data="back:main")],
    ])
