"""Keyboard builders for the Search wizard."""
from __future__ import annotations

from typing import Dict, List, Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


# ── entry ──────────────────────────────────────────────────────────────

def search_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔍 بحث جديد",        callback_data="srch:new"),
            InlineKeyboardButton(text="📋 سجل البحث",       callback_data="srch:history"),
        ],
        [
            InlineKeyboardButton(text="📊 إحصائيات الروابط", callback_data="srch:stats"),
            InlineKeyboardButton(text="🔗 قاعدة الروابط",   callback_data="srch:database"),
        ],
        [InlineKeyboardButton(text="⬅️ رجوع", callback_data="back:main")],
    ])


# ── wizard step 1: account selection ──────────────────────────────────

def accounts_kb(accounts: List[Dict], selected: List[int]) -> InlineKeyboardMarkup:
    rows = []
    for acc in accounts:
        acc_id = acc["id"]
        phone  = acc.get("phone", "")
        masked = f"{phone[:4]}***{phone[-4:]}" if len(phone) >= 8 else phone
        ok_ico = "🟢" if acc.get("is_connected") else "🔴"
        chk    = "✅ " if acc_id in selected else "⬜ "
        rows.append([
            InlineKeyboardButton(
                text=f"{chk}{ok_ico} {masked}",
                callback_data=f"srch:toggle_acc:{acc_id}",
            )
        ])

    rows.append([
        InlineKeyboardButton(text="✅ تحديد الكل",  callback_data="srch:select_all"),
        InlineKeyboardButton(text="⬛ إلغاء الكل",  callback_data="srch:deselect_all"),
    ])
    rows.append([
        InlineKeyboardButton(text="❌ إلغاء",        callback_data="srch:cancel"),
        InlineKeyboardButton(text="التالي ➡️",       callback_data="srch:go:platform"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── wizard step 2: platform ────────────────────────────────────────────

def platform_kb(selected: str = "both") -> InlineKeyboardMarkup:
    def dot(v): return "🔵 " if selected == v else "⚪ "
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{dot('telegram')}📱 Telegram فقط",
                              callback_data="srch:set_platform:telegram")],
        [InlineKeyboardButton(text=f"{dot('whatsapp')}💬 WhatsApp فقط",
                              callback_data="srch:set_platform:whatsapp")],
        [InlineKeyboardButton(text=f"{dot('both')}📱💬 Telegram + WhatsApp",
                              callback_data="srch:set_platform:both")],
        [
            InlineKeyboardButton(text="⬅️ السابق", callback_data="srch:go:accounts"),
            InlineKeyboardButton(text="التالي ➡️", callback_data="srch:go:link_types"),
        ],
    ])


# ── wizard step 3: link types ──────────────────────────────────────────

def link_types_kb(
    platform: str,
    tg_types: List[str],
    wa_types: List[str],
) -> InlineKeyboardMarkup:
    rows = []

    if platform in ("telegram", "both"):
        rows.append([InlineKeyboardButton(text="📱 Telegram", callback_data="srch:noop")])
        all_tg = {"tg_public_group", "tg_channel", "tg_private_group"}
        for val, label in [
            ("tg_public_group",  "👥 مجموعات عامة"),
            ("tg_channel",       "📢 قنوات"),
            ("tg_private_group", "🔒 مجموعات خاصة"),
        ]:
            chk = "✅ " if val in tg_types else "⬜ "
            rows.append([InlineKeyboardButton(
                text=f"{chk}{label}", callback_data=f"srch:toggle_tg:{val}"
            )])
        tg_all_chk = "☑️" if all_tg.issubset(tg_types) else "⬜"
        rows.append([InlineKeyboardButton(
            text=f"{tg_all_chk} كل أنواع Telegram", callback_data="srch:tg_all"
        )])

    if platform in ("whatsapp", "both"):
        rows.append([InlineKeyboardButton(text="💬 WhatsApp", callback_data="srch:noop")])
        all_wa = {"wa_group", "wa_channel"}
        for val, label in [
            ("wa_group",   "👥 مجموعات"),
            ("wa_channel", "📢 قنوات"),
        ]:
            chk = "✅ " if val in wa_types else "⬜ "
            rows.append([InlineKeyboardButton(
                text=f"{chk}{label}", callback_data=f"srch:toggle_wa:{val}"
            )])
        wa_all_chk = "☑️" if all_wa.issubset(wa_types) else "⬜"
        rows.append([InlineKeyboardButton(
            text=f"{wa_all_chk} كل أنواع WhatsApp", callback_data="srch:wa_all"
        )])

    rows.append([
        InlineKeyboardButton(text="⬅️ السابق", callback_data="srch:go:platform"),
        InlineKeyboardButton(text="التالي ➡️", callback_data="srch:go:depth"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── wizard step 4: search depth ────────────────────────────────────────

def depth_kb(selected: str = "normal") -> InlineKeyboardMarkup:
    def dot(v): return "🔵 " if selected == v else "⚪ "
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{dot('fast')}⚡ سريع — سرعة أعلى ونطاق أقل",
            callback_data="srch:set_depth:fast",
        )],
        [InlineKeyboardButton(
            text=f"{dot('normal')}🔎 عادي — توازن بين السرعة والشمول",
            callback_data="srch:set_depth:normal",
        )],
        [InlineKeyboardButton(
            text=f"{dot('deep')}🧠 عميق — أوسع وأكثر شمولاً (يستغرق وقتاً أطول)",
            callback_data="srch:set_depth:deep",
        )],
        [
            InlineKeyboardButton(text="⬅️ السابق", callback_data="srch:go:link_types"),
            InlineKeyboardButton(text="التالي ➡️", callback_data="srch:go:timerange"),
        ],
    ])


# ── wizard step 5: time range ──────────────────────────────────────────

def timerange_kb(selected: str = "month") -> InlineKeyboardMarkup:
    def dot(v): return "🔵 " if selected == v else "⚪ "
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{dot('today')}📅 آخر يوم",    callback_data="srch:set_tr:today")],
        [InlineKeyboardButton(text=f"{dot('week')}📅 آخر أسبوع",  callback_data="srch:set_tr:week")],
        [InlineKeyboardButton(text=f"{dot('month')}📅 آخر شهر",    callback_data="srch:set_tr:month")],
        [InlineKeyboardButton(text=f"{dot('year')}📅 آخر سنة",    callback_data="srch:set_tr:year")],
        [InlineKeyboardButton(text=f"{dot('custom')}📅 تحديد يدوي", callback_data="srch:set_tr:custom")],
        [
            InlineKeyboardButton(text="⬅️ السابق", callback_data="srch:go:depth"),
            InlineKeyboardButton(text="التالي ➡️", callback_data="srch:go:max_results"),
        ],
    ])


# ── wizard step 6: max results ─────────────────────────────────────────

def max_results_kb(selected: int = 1000) -> InlineKeyboardMarkup:
    def dot(v): return "🔵 " if selected == v else "⚪ "
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"{dot(100)}📊 100",       callback_data="srch:set_max:100"),
            InlineKeyboardButton(text=f"{dot(500)}📊 500",       callback_data="srch:set_max:500"),
        ],
        [
            InlineKeyboardButton(text=f"{dot(1000)}📊 1000",     callback_data="srch:set_max:1000"),
            InlineKeyboardButton(text=f"{dot(0)}📊 بدون حد",     callback_data="srch:set_max:0"),
        ],
        [
            InlineKeyboardButton(text="⬅️ السابق", callback_data="srch:go:timerange"),
            InlineKeyboardButton(text="تأكيد ✅",  callback_data="srch:confirm"),
        ],
    ])


# ── step 7: confirmation ───────────────────────────────────────────────

def confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🚀 بدء البحث", callback_data="srch:do_start"),
            InlineKeyboardButton(text="❌ إلغاء",      callback_data="srch:cancel"),
        ]
    ])


# ── running job ────────────────────────────────────────────────────────

def running_kb(job_id: int, paused: bool = False) -> InlineKeyboardMarkup:
    if paused:
        row = [
            InlineKeyboardButton(text="▶️ استمرار",      callback_data=f"srch:resume:{job_id}"),
            InlineKeyboardButton(text="⏹️ إيقاف",        callback_data=f"srch:stop:{job_id}"),
        ]
    else:
        row = [
            InlineKeyboardButton(text="⏸️ إيقاف مؤقت", callback_data=f"srch:pause:{job_id}"),
            InlineKeyboardButton(text="⏹️ إيقاف",       callback_data=f"srch:stop:{job_id}"),
        ]
    return InlineKeyboardMarkup(inline_keyboard=[row])


# ── history ────────────────────────────────────────────────────────────

def history_kb(jobs: list) -> InlineKeyboardMarkup:
    rows = []
    STATUS_ICONS = {
        "completed": "✅", "running": "🟡", "paused": "🟠",
        "failed": "🔴", "cancelled": "⚪", "pending": "🔵",
    }
    for job in jobs:
        icon  = STATUS_ICONS.get(job.status, "❓")
        dt    = job.created_at.strftime("%m/%d %H:%M") if job.created_at else "—"
        label = f"{icon} #{job.id} | {dt} | جديدة:{job.new_count} ♻️:{job.duplicate_count}"
        rows.append([
            InlineKeyboardButton(text=label, callback_data=f"srch:view:{job.id}")
        ])
    rows.append([
        InlineKeyboardButton(text="🔍 بحث جديد", callback_data="srch:new"),
        InlineKeyboardButton(text="⬅️ رجوع",     callback_data="menu:search"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── job detail ─────────────────────────────────────────────────────────

def job_detail_kb(job_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📥 Telegram", callback_data=f"srch:export_tg:{job_id}"),
            InlineKeyboardButton(text="📥 WhatsApp",  callback_data=f"srch:export_wa:{job_id}"),
        ],
        [
            InlineKeyboardButton(text="📥 الكل CSV",  callback_data=f"srch:export_all:{job_id}"),
        ],
        [
            InlineKeyboardButton(text="⬅️ السجل",    callback_data="srch:history"),
            InlineKeyboardButton(text="🔍 بحث جديد", callback_data="srch:new"),
        ],
    ])
