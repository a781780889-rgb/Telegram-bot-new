"""
Search handler – full multi-step wizard inside the Telegram bot.

Wizard flow:
  menu:search
    └─ srch:new       → step 1: accounts
    │    srch:go:platform  → step 2: platform
    │    srch:go:link_types → step 3: link types
    │    srch:go:depth     → step 4: search depth
    │    srch:go:timerange → step 5: time range
    │       (custom date → text FSM states)
    │    srch:go:max_results → step 6: max results
    │    srch:confirm  → step 7: confirm
    │    srch:do_start → create job → show live progress
    └─ srch:history    → list past jobs
    └─ srch:view:<id>  → job detail
    └─ srch:stats      → link stats
    └─ srch:pause/resume/stop:<id> → job control
    └─ srch:export_tg/wa/all:<id>  → send file
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import List, Optional

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile
from loguru import logger

from app.bot.keyboards.search_keyboards import (
    accounts_kb,
    confirm_kb,
    depth_kb,
    history_kb,
    job_detail_kb,
    link_types_kb,
    max_results_kb,
    platform_kb,
    running_kb,
    search_main_menu,
    timerange_kb,
)
from app.bot.states.states import SearchWizardStates
from app.database.database import AsyncSessionLocal
from app.database.repositories.account_repo import AccountRepository
from app.database.repositories.link_repo import LinkRepository
from app.database.repositories.search_repo import SearchRepository
from app.services.search.search_job_manager import search_job_manager

router = Router()

# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════

async def _load_accounts(user_id: int) -> List[dict]:
    """Return the user's accounts as plain dicts for keyboard rendering."""
    async with AsyncSessionLocal() as db:
        repo   = AccountRepository(db)
        accs   = await repo.list_by_user(user_id)
        return [
            {"id": a.id, "phone": a.phone or "", "is_connected": a.is_connected}
            for a in accs
        ]


def _wizard_default() -> dict:
    return {
        "account_ids": [],
        "platform":    "both",
        "tg_types":    ["tg_public_group", "tg_channel", "tg_private_group"],
        "wa_types":    ["wa_group", "wa_channel"],
        "depth":       "normal",
        "time_range":  "month",
        "date_from":   None,
        "date_to":     None,
        "max_results": 1000,
    }


async def _safe_edit(cb: types.CallbackQuery, text: str, kb=None):
    """Edit the callback message; ignore 'message is not modified' errors."""
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        pass


# ══════════════════════════════════════════════════════════════════════
# Entry: menu:search
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "menu:search")
async def search_menu(cb: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await _safe_edit(cb, "🔍 قسم البحث\n\nابحث عن روابط Telegram وWhatsApp وخزّنها بلا تكرار.",
                     search_main_menu())
    await cb.answer()


# ══════════════════════════════════════════════════════════════════════
# Wizard Step 1 – Account Selection
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "srch:new")
async def wizard_start(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(SearchWizardStates.SELECTING_ACCOUNTS)
    await state.set_data(_wizard_default())

    accounts = await _load_accounts(cb.from_user.id)
    if not accounts:
        await _safe_edit(
            cb,
            "⚠️ لا توجد حسابات مضافة.\n\nأضف حساباً أولاً من قسم الحسابات.",
            types.InlineKeyboardMarkup(inline_keyboard=[[
                types.InlineKeyboardButton(text="📂 الحسابات", callback_data="menu:accounts"),
                types.InlineKeyboardButton(text="⬅️ رجوع",    callback_data="menu:search"),
            ]]),
        )
        await cb.answer()
        return

    data = await state.get_data()
    await _safe_edit(
        cb,
        "🔍 إنشاء بحث جديد\n━━━━━━━━━━━━━━━━\nالخطوة 1 من 6: تحديد الحسابات\n\nاختر الحساب أو الحسابات التي ستُستخدم في البحث:",
        accounts_kb(accounts, data["account_ids"]),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("srch:toggle_acc:"))
async def toggle_account(cb: types.CallbackQuery, state: FSMContext):
    acc_id = int(cb.data.split(":")[-1])
    data   = await state.get_data()
    sel    = data.get("account_ids", [])

    if acc_id in sel:
        sel.remove(acc_id)
    else:
        sel.append(acc_id)

    await state.update_data(account_ids=sel)
    accounts = await _load_accounts(cb.from_user.id)
    await _safe_edit(
        cb,
        "🔍 الخطوة 1 من 6: تحديد الحسابات",
        accounts_kb(accounts, sel),
    )
    await cb.answer()


@router.callback_query(F.data == "srch:select_all")
async def select_all_accounts(cb: types.CallbackQuery, state: FSMContext):
    accounts = await _load_accounts(cb.from_user.id)
    sel      = [a["id"] for a in accounts]
    await state.update_data(account_ids=sel)
    await _safe_edit(cb, "🔍 الخطوة 1 من 6: تحديد الحسابات", accounts_kb(accounts, sel))
    await cb.answer("✅ تم تحديد الكل")


@router.callback_query(F.data == "srch:deselect_all")
async def deselect_all_accounts(cb: types.CallbackQuery, state: FSMContext):
    await state.update_data(account_ids=[])
    accounts = await _load_accounts(cb.from_user.id)
    await _safe_edit(cb, "🔍 الخطوة 1 من 6: تحديد الحسابات", accounts_kb(accounts, []))
    await cb.answer("⬛ تم إلغاء التحديد")


# ══════════════════════════════════════════════════════════════════════
# Wizard Step 2 – Platform
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "srch:go:platform")
async def wizard_platform(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("account_ids"):
        await cb.answer("⚠️ اختر حساباً واحداً على الأقل", show_alert=True)
        return
    await state.set_state(SearchWizardStates.SELECTING_PLATFORM)
    await _safe_edit(
        cb,
        "🔍 الخطوة 2 من 6: تحديد المنصات\n\nاختر المنصة التي تريد البحث فيها:",
        platform_kb(data.get("platform", "both")),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("srch:set_platform:"))
async def set_platform(cb: types.CallbackQuery, state: FSMContext):
    platform = cb.data.split(":")[-1]
    await state.update_data(platform=platform)
    await _safe_edit(
        cb,
        "🔍 الخطوة 2 من 6: تحديد المنصات",
        platform_kb(platform),
    )
    await cb.answer()


# ══════════════════════════════════════════════════════════════════════
# Wizard Step 3 – Link Types
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "srch:go:link_types")
async def wizard_link_types(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(SearchWizardStates.SELECTING_LINK_TYPE)
    data = await state.get_data()
    await _safe_edit(
        cb,
        "🔍 الخطوة 3 من 6: أنواع الروابط\n\nحدد أنواع الروابط المطلوبة:",
        link_types_kb(data["platform"], data["tg_types"], data["wa_types"]),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("srch:toggle_tg:"))
async def toggle_tg_type(cb: types.CallbackQuery, state: FSMContext):
    val  = cb.data.split(":")[-1]
    data = await state.get_data()
    tgt  = data.get("tg_types", [])
    if val in tgt:
        tgt.remove(val)
    else:
        tgt.append(val)
    await state.update_data(tg_types=tgt)
    await _safe_edit(cb, "🔍 الخطوة 3 من 6: أنواع الروابط",
                     link_types_kb(data["platform"], tgt, data["wa_types"]))
    await cb.answer()


@router.callback_query(F.data.startswith("srch:toggle_wa:"))
async def toggle_wa_type(cb: types.CallbackQuery, state: FSMContext):
    val  = cb.data.split(":")[-1]
    data = await state.get_data()
    wat  = data.get("wa_types", [])
    if val in wat:
        wat.remove(val)
    else:
        wat.append(val)
    await state.update_data(wa_types=wat)
    await _safe_edit(cb, "🔍 الخطوة 3 من 6: أنواع الروابط",
                     link_types_kb(data["platform"], data["tg_types"], wat))
    await cb.answer()


@router.callback_query(F.data == "srch:tg_all")
async def select_all_tg_types(cb: types.CallbackQuery, state: FSMContext):
    all_tg = ["tg_public_group", "tg_channel", "tg_private_group"]
    data   = await state.get_data()
    cur    = data.get("tg_types", [])
    new    = [] if set(all_tg).issubset(cur) else all_tg
    await state.update_data(tg_types=new)
    await _safe_edit(cb, "🔍 الخطوة 3 من 6: أنواع الروابط",
                     link_types_kb(data["platform"], new, data["wa_types"]))
    await cb.answer()


@router.callback_query(F.data == "srch:wa_all")
async def select_all_wa_types(cb: types.CallbackQuery, state: FSMContext):
    all_wa = ["wa_group", "wa_channel"]
    data   = await state.get_data()
    cur    = data.get("wa_types", [])
    new    = [] if set(all_wa).issubset(cur) else all_wa
    await state.update_data(wa_types=new)
    await _safe_edit(cb, "🔍 الخطوة 3 من 6: أنواع الروابط",
                     link_types_kb(data["platform"], data["tg_types"], new))
    await cb.answer()


# ══════════════════════════════════════════════════════════════════════
# Wizard Step 4 – Search Depth
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "srch:go:depth")
async def wizard_depth(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(SearchWizardStates.SELECTING_DEPTH)
    data = await state.get_data()
    await _safe_edit(
        cb,
        "🔍 الخطوة 4 من 6: نوع البحث\n\nاختر مستوى عمق البحث:",
        depth_kb(data.get("depth", "normal")),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("srch:set_depth:"))
async def set_depth(cb: types.CallbackQuery, state: FSMContext):
    depth = cb.data.split(":")[-1]
    await state.update_data(depth=depth)
    await _safe_edit(cb, "🔍 الخطوة 4 من 6: نوع البحث", depth_kb(depth))
    await cb.answer()


# ══════════════════════════════════════════════════════════════════════
# Wizard Step 5 – Time Range
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "srch:go:timerange")
async def wizard_timerange(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(SearchWizardStates.SELECTING_TIME_RANGE)
    data = await state.get_data()
    await _safe_edit(
        cb,
        "🔍 الخطوة 5 من 6: النطاق الزمني\n\nاختر الفترة الزمنية للبحث:",
        timerange_kb(data.get("time_range", "month")),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("srch:set_tr:"))
async def set_timerange(cb: types.CallbackQuery, state: FSMContext):
    tr = cb.data.split(":")[-1]
    await state.update_data(time_range=tr, date_from=None, date_to=None)

    if tr == "custom":
        await state.set_state(SearchWizardStates.CUSTOM_DATE_FROM)
        await cb.message.edit_text(
            "📅 أدخل تاريخ البداية بالصيغة:\nYYYY-MM-DD\n\nمثال: 2026-01-01",
        )
    else:
        await _safe_edit(cb, "🔍 الخطوة 5 من 6: النطاق الزمني", timerange_kb(tr))
    await cb.answer()


@router.message(SearchWizardStates.CUSTOM_DATE_FROM)
async def get_custom_date_from(msg: types.Message, state: FSMContext):
    try:
        dt = datetime.strptime(msg.text.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        await msg.answer("❌ صيغة التاريخ غير صحيحة. أدخل بالصيغة YYYY-MM-DD\nمثال: 2026-01-01")
        return
    await state.update_data(date_from=dt.isoformat())
    await state.set_state(SearchWizardStates.CUSTOM_DATE_TO)
    await msg.answer("📅 أدخل تاريخ النهاية بالصيغة:\nYYYY-MM-DD\n\nمثال: 2026-07-29")


@router.message(SearchWizardStates.CUSTOM_DATE_TO)
async def get_custom_date_to(msg: types.Message, state: FSMContext):
    try:
        dt = datetime.strptime(msg.text.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        await msg.answer("❌ صيغة التاريخ غير صحيحة. أدخل بالصيغة YYYY-MM-DD")
        return

    data = await state.get_data()
    df   = datetime.fromisoformat(data["date_from"]) if data.get("date_from") else None

    if df and dt < df:
        await msg.answer("❌ تاريخ النهاية يجب أن يكون بعد تاريخ البداية.")
        return

    await state.update_data(date_to=dt.isoformat())
    await state.set_state(SearchWizardStates.SELECTING_MAX_RESULTS)
    await msg.answer(
        f"✅ التواريخ:\nمن: {data['date_from'][:10]}\nإلى: {dt.date()}\n\n"
        "اختر الحد الأقصى للنتائج:",
        reply_markup=max_results_kb(),
    )


# ══════════════════════════════════════════════════════════════════════
# Wizard Step 6 – Max Results
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "srch:go:max_results")
async def wizard_max_results(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(SearchWizardStates.SELECTING_MAX_RESULTS)
    data = await state.get_data()
    await _safe_edit(
        cb,
        "🔍 الخطوة 6 من 6: الحد الأقصى للنتائج\n\nاختر أقصى عدد للروابط:",
        max_results_kb(data.get("max_results", 1000)),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("srch:set_max:"))
async def set_max_results(cb: types.CallbackQuery, state: FSMContext):
    val = int(cb.data.split(":")[-1])
    await state.update_data(max_results=val)
    await _safe_edit(
        cb,
        "🔍 الخطوة 6 من 6: الحد الأقصى للنتائج",
        max_results_kb(val),
    )
    await cb.answer()


# ══════════════════════════════════════════════════════════════════════
# Wizard Step 7 – Confirm
# ══════════════════════════════════════════════════════════════════════

_PLATFORM_LABELS = {
    "telegram": "📱 Telegram",
    "whatsapp": "💬 WhatsApp",
    "both":     "📱💬 Telegram + WhatsApp",
}
_DEPTH_LABELS = {"fast": "⚡ سريع", "normal": "🔎 عادي", "deep": "🧠 عميق"}
_TR_LABELS = {
    "today": "آخر يوم", "week": "آخر أسبوع",
    "month": "آخر شهر", "year": "آخر سنة", "custom": "تاريخ مخصص",
}


@router.callback_query(F.data == "srch:confirm")
async def wizard_confirm(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(SearchWizardStates.CONFIRMING)
    data   = await state.get_data()
    n_acc  = len(data.get("account_ids", []))
    plat   = _PLATFORM_LABELS.get(data["platform"], data["platform"])
    depth  = _DEPTH_LABELS.get(data["depth"], data["depth"])
    tr     = _TR_LABELS.get(data["time_range"], data["time_range"])
    mx     = data["max_results"] or "بدون حد"

    text = (
        "🔍 تأكيد عملية البحث\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👤 الحسابات:       {n_acc}\n"
        f"📡 المنصات:        {plat}\n"
        f"🔍 نوع البحث:      {depth}\n"
        f"📅 الفترة:         {tr}\n"
        f"📊 الحد الأقصى:   {mx}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "هل تريد بدء البحث؟"
    )
    await _safe_edit(cb, text, confirm_kb())
    await cb.answer()


# ══════════════════════════════════════════════════════════════════════
# Start the job
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "srch:do_start")
async def do_start(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()

    # Resolve link_types list from selected types
    link_types: list[str] = []
    if data["platform"] in ("telegram", "both"):
        link_types += data.get("tg_types", [])
    if data["platform"] in ("whatsapp", "both"):
        link_types += data.get("wa_types", [])

    # Parse custom dates
    date_from: Optional[datetime] = None
    date_to:   Optional[datetime] = None
    if data.get("date_from"):
        date_from = datetime.fromisoformat(data["date_from"])
    if data.get("date_to"):
        date_to   = datetime.fromisoformat(data["date_to"])

    # Create job in DB
    async with AsyncSessionLocal() as db:
        repo = SearchRepository(db)
        job  = await repo.create(
            user_id=cb.from_user.id,
            account_ids=data["account_ids"],
            platforms=data["platform"],
            link_types=link_types,
            search_type=data["depth"],
            date_range=data["time_range"],
            date_from=date_from,
            date_to=date_to,
            max_results=data["max_results"] or 99_999,
        )

    await state.set_state(SearchWizardStates.RUNNING)
    await state.update_data(job_id=job.id)

    # Send initial progress message (this is what the manager will edit)
    text = (
        f"🔴 البحث يعمل الآن — #JOB{job.id}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 المكتشفة: 0\n"
        "✅ جديدة:     0\n"
        "♻️ مكررة:     0\n"
        "❌ غير صالحة: 0\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📱 Telegram: 0   💬 WA: 0\n"
    )
    prog_msg = await cb.message.edit_text(text, reply_markup=running_kb(job.id))
    search_job_manager.start(job.id, cb.message.chat.id, prog_msg.message_id)
    await cb.answer("🚀 تم بدء البحث!")


# ══════════════════════════════════════════════════════════════════════
# Job Control (pause / resume / stop)
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("srch:pause:"))
async def pause_job(cb: types.CallbackQuery):
    job_id = int(cb.data.split(":")[-1])
    if search_job_manager.pause(job_id):
        await cb.answer("⏸️ تم الإيقاف المؤقت")
        try:
            await cb.message.edit_reply_markup(reply_markup=running_kb(job_id, paused=True))
        except TelegramBadRequest:
            pass
    else:
        await cb.answer("⚠️ البحث ليس نشطاً", show_alert=True)


@router.callback_query(F.data.startswith("srch:resume:"))
async def resume_job(cb: types.CallbackQuery):
    job_id = int(cb.data.split(":")[-1])
    if search_job_manager.resume(job_id):
        await cb.answer("▶️ تم الاستمرار")
        try:
            await cb.message.edit_reply_markup(reply_markup=running_kb(job_id, paused=False))
        except TelegramBadRequest:
            pass
    else:
        await cb.answer("⚠️ البحث ليس متوقفاً", show_alert=True)


@router.callback_query(F.data.startswith("srch:stop:"))
async def stop_job(cb: types.CallbackQuery):
    job_id = int(cb.data.split(":")[-1])
    if search_job_manager.stop(job_id):
        await cb.answer("⏹️ جاري إيقاف البحث…")
    else:
        await cb.answer("⚠️ لا يوجد بحث نشط بهذا المعرف", show_alert=True)


# ══════════════════════════════════════════════════════════════════════
# History
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "srch:history")
async def search_history(cb: types.CallbackQuery, state: FSMContext):
    await state.clear()
    async with AsyncSessionLocal() as db:
        repo = SearchRepository(db)
        jobs = await repo.list_by_user(cb.from_user.id, limit=15)

    if not jobs:
        await _safe_edit(
            cb,
            "📋 سجل البحث\n\nلم تُنفَّذ أي عملية بحث بعد.",
            types.InlineKeyboardMarkup(inline_keyboard=[[
                types.InlineKeyboardButton(text="🔍 بدء بحث جديد", callback_data="srch:new"),
                types.InlineKeyboardButton(text="⬅️ رجوع", callback_data="menu:search"),
            ]]),
        )
    else:
        await _safe_edit(cb, "📋 سجل عمليات البحث (آخر 15):", history_kb(jobs))
    await cb.answer()


# ══════════════════════════════════════════════════════════════════════
# Job Detail
# ══════════════════════════════════════════════════════════════════════

_STATUS_AR = {
    "pending":   "🔵 في الانتظار",
    "running":   "🟡 يعمل",
    "paused":    "🟠 متوقف مؤقتاً",
    "completed": "✅ مكتمل",
    "failed":    "🔴 فشل",
    "cancelled": "⚪ ملغي",
}


@router.callback_query(F.data.startswith("srch:view:"))
async def view_job(cb: types.CallbackQuery):
    job_id = int(cb.data.split(":")[-1])
    async with AsyncSessionLocal() as db:
        repo = SearchRepository(db)
        job  = await repo.get_by_id(job_id)

    if not job:
        await cb.answer("⚠️ لم يتم العثور على العملية", show_alert=True)
        return

    plat  = _PLATFORM_LABELS.get(job.platforms, job.platforms)
    depth = _DEPTH_LABELS.get(job.search_type, job.search_type)
    tr    = _TR_LABELS.get(job.date_range or "", "—")
    start = job.started_at.strftime("%Y-%m-%d %H:%M") if job.started_at else "—"
    end   = job.completed_at.strftime("%H:%M") if job.completed_at else "—"
    dur   = ""
    if job.started_at and job.completed_at:
        secs = int((job.completed_at - job.started_at).total_seconds())
        dur  = f" ({secs // 60}د {secs % 60}ث)"

    dup_pct = (
        round(job.duplicate_count / job.found_count * 100) if job.found_count else 0
    )

    text = (
        f"📋 تفاصيل البحث #{job.id}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 الحالة:     {_STATUS_AR.get(job.status, job.status)}\n"
        f"📡 المنصات:    {plat}\n"
        f"🔍 النوع:      {depth}\n"
        f"📅 الفترة:     {tr}\n"
        f"⏰ البداية:    {start}{dur}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 المكتشفة:   {job.found_count}\n"
        f"✅ جديدة:      {job.new_count}\n"
        f"♻️ مكررة:      {job.duplicate_count} ({dup_pct}%)\n"
        f"❌ غير صالحة:  {job.invalid_count}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📱 Telegram:   {job.tg_count}\n"
        f"💬 WhatsApp:   {job.wa_count}\n"
    )
    if job.error_message:
        text += f"\n⚠️ خطأ: {job.error_message[:200]}"

    await _safe_edit(cb, text, job_detail_kb(job_id))
    await cb.answer()


# ══════════════════════════════════════════════════════════════════════
# Statistics
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "srch:stats")
async def search_stats(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    async with AsyncSessionLocal() as db:
        sr    = SearchRepository(db)
        lr    = LinkRepository(db)
        sjobs = await sr.get_user_stats(user_id)
        slink = await lr.get_user_link_stats(user_id)

    dup_pct = (
        round(sjobs["total_dup"] / sjobs["total_found"] * 100)
        if sjobs["total_found"] else 0
    )
    text = (
        "📊 إحصائيات الروابط والبحث\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔗 إجمالي الروابط:       {slink['total']}\n"
        f"📱 Telegram:             {slink['telegram']}\n"
        f"💬 WhatsApp:             {slink['whatsapp']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔍 عمليات البحث:         {sjobs['total_jobs']}\n"
        f"📊 إجمالي المكتشفة:      {sjobs['total_found']}\n"
        f"✅ روابط جديدة:          {sjobs['total_new']}\n"
        f"♻️ روابط مكررة:          {sjobs['total_dup']} ({dup_pct}%)\n"
    )
    await _safe_edit(
        cb, text,
        types.InlineKeyboardMarkup(inline_keyboard=[[
            types.InlineKeyboardButton(text="⬅️ رجوع", callback_data="menu:search")
        ]]),
    )
    await cb.answer()


# ══════════════════════════════════════════════════════════════════════
# Export
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("srch:export_"))
async def export_links(cb: types.CallbackQuery):
    parts  = cb.data.split(":")        # ["srch", "export_tg", "123"]
    action = parts[1]                  # "export_tg" | "export_wa" | "export_all"
    job_id = int(parts[2])

    platform_map = {
        "export_tg":  "telegram",
        "export_wa":  "whatsapp",
        "export_all": None,
    }
    platform = platform_map.get(action)

    await cb.answer("⏳ جاري إنشاء الملف…")

    try:
        content, fname = await search_job_manager.build_export_file(job_id, platform)
    except Exception as e:
        logger.error(f"export error job {job_id}: {e}")
        await cb.answer(f"❌ فشل التصدير: {e}", show_alert=True)
        return

    if not content:
        await cb.answer("⚠️ لا توجد روابط للتصدير", show_alert=True)
        return

    await cb.message.answer_document(
        document=BufferedInputFile(content, filename=fname),
        caption=f"📥 {fname}\n🔗 {content.count(b'http')} رابط",
    )


# ══════════════════════════════════════════════════════════════════════
# Cancel / no-op
# ══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data == "srch:cancel")
async def cancel_wizard(cb: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await _safe_edit(
        cb,
        "❌ تم إلغاء البحث.",
        types.InlineKeyboardMarkup(inline_keyboard=[[
            types.InlineKeyboardButton(text="🔍 بحث جديد", callback_data="srch:new"),
            types.InlineKeyboardButton(text="⬅️ رجوع",    callback_data="menu:search"),
        ]]),
    )
    await cb.answer()


@router.callback_query(F.data == "srch:noop")
async def noop(cb: types.CallbackQuery):
    await cb.answer()


# Back-navigation shorthands
@router.callback_query(F.data == "srch:go:accounts")
async def back_to_accounts(cb: types.CallbackQuery, state: FSMContext):
    await wizard_start(cb, state)


@router.callback_query(F.data == "srch:go:depth")
async def back_to_depth(cb: types.CallbackQuery, state: FSMContext):
    await wizard_depth(cb, state)


@router.callback_query(F.data == "srch:go:timerange")
async def back_to_timerange(cb: types.CallbackQuery, state: FSMContext):
    await wizard_timerange(cb, state)
