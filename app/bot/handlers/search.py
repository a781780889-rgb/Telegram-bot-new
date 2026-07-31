"""
Search wizard handler.

Intercepted callbacks (registered BEFORE the generic menu router):
  menu:search          — entry point
  s:ac:*               — Step 1: account selection
  s:pl:*               — Step 2: platform
  s:lt:*               — Step 3: link types
  s:dp:*               — Step 4: depth
  s:pd:*               — Step 5: period
  s:bk:{n}             — go back to wizard step n
  s:cf                 — confirm → create job → start engine
  s:cx                 — cancel wizard
  s:ps:{id}            — pause running job
  s:rs:{id}            — resume paused job
  s:st:{id}            — stop job
  s:ex:tg:{id}         — export Telegram links
  s:ex:wa:{id}         — export WhatsApp links
  s:ex:al:{id}         — export all links (CSV)

Message handlers (FSM states):
  SearchWizardStates.CUSTOM_DATE_FROM  — text: date_from
  SearchWizardStates.CUSTOM_DATE_TO    — text: date_to
"""

from __future__ import annotations

import asyncio
import csv
import io
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from aiogram import Bot, F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup
from loguru import logger

from app.bot.keyboards.main_menu import get_back_button
from app.bot.keyboards.search_keyboards import (
    accounts_keyboard,
    confirm_keyboard,
    depth_keyboard,
    link_types_keyboard,
    paused_keyboard,
    period_keyboard,
    platform_keyboard,
    results_keyboard,
    running_keyboard,
)
from app.bot.states.states import SearchWizardStates
from app.database.database import AsyncSessionLocal
from app.database.models.search import LinkPlatform, SearchPlatform
from app.database.repositories.account_repo import AccountRepository
from app.database.repositories.link_repo import LinkRepository
from app.database.repositories.search_repo import SearchJobRepository
from app.services.search.engine import SearchEngine, get_engine

router = Router()

# ─── helpers ─────────────────────────────────────────────────────────────

_PLATFORM_LABELS = {"tg": "Telegram", "wa": "WhatsApp", "bo": "Telegram + WhatsApp"}
_PLATFORM_DB     = {"tg": "telegram",  "wa": "whatsapp",  "bo": "both"}
_DEPTH_LABELS    = {"fa": "⚡ سريع",    "no": "🔎 عادي",    "de": "🧠 عميق"}
_DEPTH_DB        = {"fa": "fast",       "no": "normal",     "de": "deep"}
_PERIOD_LABELS   = {
    "dy": "آخر يوم", "wk": "آخر أسبوع",
    "mn": "آخر شهر", "yr": "آخر سنة",  "cu": "تاريخ مخصص",
}
_PERIOD_DB       = {
    "dy": "day",    "wk": "week",
    "mn": "month",  "yr": "year", "cu": "custom",
}


def _default_link_types() -> Dict[str, bool]:
    return {
        "tg_groups":   True,
        "tg_channels": True,
        "tg_private":  True,
        "wa_groups":   True,
        "wa_channels": True,
    }


async def _load_accounts(user_id: int) -> list:
    async with AsyncSessionLocal() as db:
        repo   = AccountRepository(db)
        return await repo.list_by_user(user_id)


def _wizard_summary(data: Dict[str, Any]) -> str:
    acc_count = len(data.get("selected_accounts", []))
    platform  = _PLATFORM_LABELS.get(data.get("platform", "tg"), "—")
    depth     = _DEPTH_LABELS.get(data.get("depth", "no"), "—")
    period    = _PERIOD_LABELS.get(data.get("period", "wk"), "—")

    lt  = data.get("link_types", _default_link_types())
    active = [k for k, v in lt.items() if v]
    lt_str = ", ".join(active) if active else "لا شيء"

    lines = [
        "📋 ملخص عملية البحث",
        "",
        f"👤 الحسابات المحددة:  {acc_count}",
        f"📡 المنصة:           {platform}",
        f"🔗 أنواع الروابط:    {lt_str}",
        f"🔍 عمق البحث:       {depth}",
        f"📅 الفترة:           {period}",
    ]
    if data.get("period") == "cu":
        df = data.get("date_from", "—")
        dt = data.get("date_to",   "—")
        lines.append(f"   من: {df}  إلى: {dt}")

    lines += ["", "هل تريد بدء عملية البحث؟"]
    return "\n".join(lines)


# ─── Step 0: entry ────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu:search")
async def search_entry(callback: types.CallbackQuery, state: FSMContext) -> None:
    user_id  = callback.from_user.id
    accounts = await _load_accounts(user_id)

    if not accounts:
        await callback.message.edit_text(
            "⚠️ لا توجد حسابات مضافة.\n\nأضف حساباً أولاً من قسم الحسابات.",
            reply_markup=get_back_button("main"),
        )
        await callback.answer()
        return

    await state.set_state(SearchWizardStates.SELECTING_ACCOUNTS)
    await state.update_data(
        selected_accounts=[],
        platform="tg",
        link_types=_default_link_types(),
        depth="no",
        period="wk",
        date_from=None,
        date_to=None,
    )

    await callback.message.edit_text(
        "🔍 إنشاء عملية بحث جديدة\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "المرحلة 1 / 6 — تحديد الحسابات\n\n"
        "اختر الحسابات التي ستُستخدم في البحث:",
        reply_markup=accounts_keyboard(accounts, selected_ids=set()),
    )
    await callback.answer()


# ─── Step 1: account selection ────────────────────────────────────────────

@router.callback_query(
    SearchWizardStates.SELECTING_ACCOUNTS,
    F.data.startswith("s:ac:t:"),
)
async def toggle_account(callback: types.CallbackQuery, state: FSMContext) -> None:
    acc_id   = int(callback.data.split(":")[-1])
    data     = await state.get_data()
    selected = set(data.get("selected_accounts", []))

    if acc_id in selected:
        selected.discard(acc_id)
    else:
        selected.add(acc_id)

    await state.update_data(selected_accounts=list(selected))

    accounts = await _load_accounts(callback.from_user.id)
    await callback.message.edit_reply_markup(
        reply_markup=accounts_keyboard(accounts, selected_ids=selected)
    )
    await callback.answer()


@router.callback_query(SearchWizardStates.SELECTING_ACCOUNTS, F.data == "s:ac:all")
async def select_all_accounts(callback: types.CallbackQuery, state: FSMContext) -> None:
    accounts = await _load_accounts(callback.from_user.id)
    all_ids  = {acc.id for acc in accounts}
    await state.update_data(selected_accounts=list(all_ids))
    await callback.message.edit_reply_markup(
        reply_markup=accounts_keyboard(accounts, selected_ids=all_ids)
    )
    await callback.answer("✅ تم تحديد جميع الحسابات")


@router.callback_query(SearchWizardStates.SELECTING_ACCOUNTS, F.data == "s:ac:nn")
async def deselect_all_accounts(callback: types.CallbackQuery, state: FSMContext) -> None:
    accounts = await _load_accounts(callback.from_user.id)
    await state.update_data(selected_accounts=[])
    await callback.message.edit_reply_markup(
        reply_markup=accounts_keyboard(accounts, selected_ids=set())
    )
    await callback.answer("تم إلغاء تحديد الكل")


@router.callback_query(SearchWizardStates.SELECTING_ACCOUNTS, F.data == "s:ac:nx")
async def accounts_next(callback: types.CallbackQuery, state: FSMContext) -> None:
    data     = await state.get_data()
    selected = data.get("selected_accounts", [])

    if not selected:
        await callback.answer("⚠️ يجب تحديد حساب واحد على الأقل", show_alert=True)
        return

    await state.set_state(SearchWizardStates.SELECTING_PLATFORM)
    platform = data.get("platform", "tg")

    await callback.message.edit_text(
        "🔍 إنشاء عملية بحث جديدة\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"المرحلة 2 / 6 — تحديد المنصة\n\n"
        "اختر المنصة التي تريد البحث فيها:",
        reply_markup=platform_keyboard(selected=platform),
    )
    await callback.answer()


# ─── Step 2: platform ─────────────────────────────────────────────────────

@router.callback_query(
    SearchWizardStates.SELECTING_PLATFORM,
    F.data.startswith("s:pl:"),
)
async def select_platform(callback: types.CallbackQuery, state: FSMContext) -> None:
    val = callback.data.split(":")[-1]
    if val == "nx":
        data     = await state.get_data()
        platform = data.get("platform", "tg")
        await state.set_state(SearchWizardStates.SELECTING_TYPES)
        await callback.message.edit_text(
            "🔍 إنشاء عملية بحث جديدة\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "المرحلة 3 / 6 — أنواع الروابط\n\n"
            "حدد أنواع الروابط التي تريد جمعها:",
            reply_markup=link_types_keyboard(platform, data.get("link_types", _default_link_types())),
        )
    elif val in ("tg", "wa", "bo"):
        await state.update_data(platform=val)
        await callback.message.edit_reply_markup(
            reply_markup=platform_keyboard(selected=val)
        )
    await callback.answer()


# ─── Step 3: link types ───────────────────────────────────────────────────

@router.callback_query(
    SearchWizardStates.SELECTING_TYPES,
    F.data.startswith("s:lt:"),
)
async def toggle_link_type(callback: types.CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    if parts[2] == "t":
        key  = parts[3]
        data = await state.get_data()
        lt   = dict(data.get("link_types", _default_link_types()))
        lt[key] = not lt.get(key, True)
        await state.update_data(link_types=lt)

        platform = data.get("platform", "tg")
        await callback.message.edit_reply_markup(
            reply_markup=link_types_keyboard(platform, lt)
        )
    elif parts[2] == "nx":
        data = await state.get_data()
        lt   = data.get("link_types", _default_link_types())
        if not any(lt.values()):
            await callback.answer("⚠️ يجب تحديد نوع واحد على الأقل", show_alert=True)
            return
        await state.set_state(SearchWizardStates.SELECTING_DEPTH)
        depth = data.get("depth", "no")
        await callback.message.edit_text(
            "🔍 إنشاء عملية بحث جديدة\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "المرحلة 4 / 6 — عمق البحث\n\n"
            "اختر نوع البحث المناسب:",
            reply_markup=depth_keyboard(selected=depth),
        )
    await callback.answer()


# ─── Step 4: depth ────────────────────────────────────────────────────────

@router.callback_query(
    SearchWizardStates.SELECTING_DEPTH,
    F.data.startswith("s:dp:"),
)
async def select_depth(callback: types.CallbackQuery, state: FSMContext) -> None:
    val = callback.data.split(":")[-1]
    if val == "nx":
        data  = await state.get_data()
        period = data.get("period", "wk")
        await state.set_state(SearchWizardStates.SELECTING_PERIOD)
        await callback.message.edit_text(
            "🔍 إنشاء عملية بحث جديدة\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "المرحلة 5 / 6 — الفترة الزمنية\n\n"
            "اختر نطاق الفترة الزمنية للبحث:",
            reply_markup=period_keyboard(selected=period),
        )
    elif val in ("fa", "no", "de"):
        await state.update_data(depth=val)
        await callback.message.edit_reply_markup(reply_markup=depth_keyboard(selected=val))
    await callback.answer()


# ─── Step 5: period ───────────────────────────────────────────────────────

@router.callback_query(
    SearchWizardStates.SELECTING_PERIOD,
    F.data.startswith("s:pd:"),
)
async def select_period(callback: types.CallbackQuery, state: FSMContext) -> None:
    val = callback.data.split(":")[-1]
    if val == "nx":
        data   = await state.get_data()
        period = data.get("period", "wk")
        if period == "cu":
            # Ask for custom date from via text
            await state.set_state(SearchWizardStates.CUSTOM_DATE_FROM)
            await callback.message.edit_text(
                "📅 التاريخ المخصص — من تاريخ\n\n"
                "أرسل تاريخ البداية بالصيغة:\n"
                "YYYY-MM-DD\n\n"
                "مثال: 2026-01-01",
                reply_markup=get_back_button("s:bk:5"),
            )
        else:
            await _go_to_confirm(callback, state, data)
    elif val in ("dy", "wk", "mn", "yr", "cu"):
        await state.update_data(period=val)
        await callback.message.edit_reply_markup(reply_markup=period_keyboard(selected=val))
    await callback.answer()


# ─── Step 5b/c: custom date input ─────────────────────────────────────────

@router.message(SearchWizardStates.CUSTOM_DATE_FROM)
async def custom_date_from(message: types.Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        await message.answer(
            "❌ صيغة التاريخ غير صحيحة.\n\nأرسل التاريخ بالصيغة: YYYY-MM-DD"
        )
        return

    await state.update_data(date_from=text)
    await state.set_state(SearchWizardStates.CUSTOM_DATE_TO)
    await message.answer(
        "📅 التاريخ المخصص — إلى تاريخ\n\n"
        "أرسل تاريخ النهاية بالصيغة:\n"
        "YYYY-MM-DD"
    )


@router.message(SearchWizardStates.CUSTOM_DATE_TO)
async def custom_date_to(message: types.Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    try:
        dt_to = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        await message.answer(
            "❌ صيغة التاريخ غير صحيحة.\n\nأرسل التاريخ بالصيغة: YYYY-MM-DD"
        )
        return

    data = await state.get_data()
    dt_from = datetime.strptime(data.get("date_from", "2000-01-01"), "%Y-%m-%d")
    if dt_to < dt_from:
        await message.answer("❌ تاريخ النهاية يجب أن يكون بعد تاريخ البداية.")
        return

    await state.update_data(date_to=text)
    await state.set_state(SearchWizardStates.CONFIRMING)
    data = await state.get_data()
    await message.answer(_wizard_summary(data), reply_markup=confirm_keyboard())


# ─── Step 6: confirmation ─────────────────────────────────────────────────

async def _go_to_confirm(
    callback: types.CallbackQuery,
    state: FSMContext,
    data: Dict[str, Any],
) -> None:
    await state.set_state(SearchWizardStates.CONFIRMING)
    await callback.message.edit_text(
        "🔍 إنشاء عملية بحث جديدة\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "المرحلة 6 / 6 — التأكيد\n\n"
        + _wizard_summary(data),
        reply_markup=confirm_keyboard(),
    )


@router.callback_query(SearchWizardStates.CONFIRMING, F.data == "s:cf")
async def confirm_search(callback: types.CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data    = await state.get_data()
    user_id = callback.from_user.id

    # Create the job
    async with AsyncSessionLocal() as db:
        repo    = SearchJobRepository(db)
        job     = await repo.create(
            user_id=user_id,
            platform=_PLATFORM_DB.get(data["platform"], "telegram"),
            depth=_DEPTH_DB.get(data["depth"], "normal"),
            period=_PERIOD_DB.get(data["period"], "week"),
            account_ids=data.get("selected_accounts", []),
            link_types_config=data.get("link_types", _default_link_types()),
            max_results=1000,
            period_from=_parse_iso_date(data.get("date_from")),
            period_to=_parse_iso_date(data.get("date_to")),
        )

    # Show the live progress placeholder
    msg = await callback.message.edit_text(
        f"🔴 البحث يعمل الآن — #{job.id}\n\n"
        "⏱️ الوقت المنقضي: 00:00:00\n"
        "📊 إجمالي الروابط: 0\n"
        "✅ جديدة:        0\n"
        "♻️ مكررة:        0\n"
        "❌ غير صالحة:   0\n\n"
        "📱 Telegram:  0\n"
        "💬 WhatsApp:  0",
        reply_markup=running_keyboard(job.id),
    )

    # Save the message reference so the engine can edit it
    async with AsyncSessionLocal() as db:
        repo = SearchJobRepository(db)
        await repo.set_message_ref(
            job.id,
            chat_id=callback.message.chat.id,
            message_id=msg.message_id,
        )

    # Clear FSM and switch to RUNNING state
    await state.set_state(SearchWizardStates.RUNNING)
    await state.update_data(active_job_id=job.id)

    # Launch the background search task
    engine = SearchEngine(job_id=job.id, bot=bot, user_id=user_id)
    asyncio.create_task(engine.run(), name=f"search_job_{job.id}")

    await callback.answer("🚀 بدأ البحث!")


# ─── Running job controls ─────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^s:ps:\d+$"))
async def pause_job(callback: types.CallbackQuery) -> None:
    job_id = int(callback.data.split(":")[-1])
    engine = get_engine(job_id)

    if engine is None:
        await callback.answer("⚠️ البحث غير نشط", show_alert=True)
        return

    engine.pause()

    async with AsyncSessionLocal() as db:
        repo = SearchJobRepository(db)
        await repo.set_paused(job_id)

    try:
        await callback.message.edit_reply_markup(reply_markup=paused_keyboard(job_id))
    except Exception:
        pass
    await callback.answer("⏸️ تم الإيقاف المؤقت")


@router.callback_query(F.data.regexp(r"^s:rs:\d+$"))
async def resume_job(callback: types.CallbackQuery) -> None:
    job_id = int(callback.data.split(":")[-1])
    engine = get_engine(job_id)

    if engine is None:
        await callback.answer("⚠️ البحث غير نشط", show_alert=True)
        return

    engine.resume()

    async with AsyncSessionLocal() as db:
        repo = SearchJobRepository(db)
        await repo.set_resumed(job_id)

    try:
        await callback.message.edit_reply_markup(reply_markup=running_keyboard(job_id))
    except Exception:
        pass
    await callback.answer("▶️ استمر البحث")


@router.callback_query(F.data.regexp(r"^s:st:\d+$"))
async def stop_job(callback: types.CallbackQuery, state: FSMContext) -> None:
    job_id = int(callback.data.split(":")[-1])
    engine = get_engine(job_id)

    if engine:
        engine.stop()

    async with AsyncSessionLocal() as db:
        repo = SearchJobRepository(db)
        await repo.set_cancelled(job_id)
        job  = await repo.get_by_id(job_id)

    await state.clear()

    text = (
        f"⏹️ تم إيقاف البحث #{job_id}\n\n"
        f"📊 الروابط المكتشفة حتى الآن: {job.found_total if job else '—'}\n"
        f"✅ جديدة: {job.found_new if job else '—'}"
    )
    try:
        await callback.message.edit_text(text, reply_markup=results_keyboard(job_id))
    except Exception:
        pass
    await callback.answer("⏹️ تم الإيقاف")


# ─── Export ───────────────────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^s:ex:(tg|wa|al):\d+$"))
async def export_links(callback: types.CallbackQuery) -> None:
    parts     = callback.data.split(":")
    export_type = parts[2]   # "tg" | "wa" | "al"
    job_id    = int(parts[3])

    await callback.answer("⏳ جاري إعداد الملف...")

    async with AsyncSessionLocal() as db:
        link_repo = LinkRepository(db)

        if export_type == "tg":
            links = await link_repo.list_by_search_and_platform(
                job_id, LinkPlatform.TELEGRAM, new_only=True
            )
            file_content = "\n".join(lk.normalized_url for lk in links).encode("utf-8")
            filename = f"telegram_links_{job_id}.txt"

        elif export_type == "wa":
            links = await link_repo.list_by_search_and_platform(
                job_id, LinkPlatform.WHATSAPP, new_only=True
            )
            file_content = "\n".join(lk.normalized_url for lk in links).encode("utf-8")
            filename = f"whatsapp_links_{job_id}.txt"

        else:  # "al" — all links as CSV
            all_links = await link_repo.list_by_search(job_id, new_only=False)
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow([
                "Platform", "Link Type", "URL", "Username",
                "Status", "Duplicate", "First Seen", "Search ID"
            ])
            for lk in all_links:
                writer.writerow([
                    lk.platform.value,
                    lk.link_type.value,
                    lk.normalized_url,
                    lk.username or "",
                    lk.status.value,
                    "yes" if lk.is_duplicate else "no",
                    lk.first_seen_at.isoformat() if lk.first_seen_at else "",
                    lk.search_id or "",
                ])
            file_content = buf.getvalue().encode("utf-8-sig")
            filename = f"all_links_{job_id}.csv"

    if not file_content.strip():
        await callback.message.answer("⚠️ لا توجد روابط للتصدير.")
        return

    doc = BufferedInputFile(file_content, filename=filename)
    await callback.message.answer_document(
        doc,
        caption=f"📥 {filename}\n\nتم التصدير بنجاح.",
    )


# ─── Back navigation ──────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("s:bk:"))
async def wizard_back(callback: types.CallbackQuery, state: FSMContext) -> None:
    step = int(callback.data.split(":")[-1])
    data = await state.get_data()

    if step == 1:
        await state.set_state(SearchWizardStates.SELECTING_ACCOUNTS)
        accounts = await _load_accounts(callback.from_user.id)
        selected = set(data.get("selected_accounts", []))
        await callback.message.edit_text(
            "🔍 إنشاء عملية بحث جديدة\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "المرحلة 1 / 6 — تحديد الحسابات:",
            reply_markup=accounts_keyboard(accounts, selected_ids=selected),
        )
    elif step == 2:
        await state.set_state(SearchWizardStates.SELECTING_PLATFORM)
        await callback.message.edit_text(
            "🔍 إنشاء عملية بحث جديدة\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "المرحلة 2 / 6 — تحديد المنصة:",
            reply_markup=platform_keyboard(selected=data.get("platform", "tg")),
        )
    elif step == 3:
        await state.set_state(SearchWizardStates.SELECTING_TYPES)
        platform = data.get("platform", "tg")
        await callback.message.edit_text(
            "🔍 إنشاء عملية بحث جديدة\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "المرحلة 3 / 6 — أنواع الروابط:",
            reply_markup=link_types_keyboard(platform, data.get("link_types", _default_link_types())),
        )
    elif step == 4:
        await state.set_state(SearchWizardStates.SELECTING_DEPTH)
        await callback.message.edit_text(
            "🔍 إنشاء عملية بحث جديدة\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "المرحلة 4 / 6 — عمق البحث:",
            reply_markup=depth_keyboard(selected=data.get("depth", "no")),
        )
    elif step == 5:
        await state.set_state(SearchWizardStates.SELECTING_PERIOD)
        await callback.message.edit_text(
            "🔍 إنشاء عملية بحث جديدة\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "المرحلة 5 / 6 — الفترة الزمنية:",
            reply_markup=period_keyboard(selected=data.get("period", "wk")),
        )

    await callback.answer()


# ─── Cancel wizard ────────────────────────────────────────────────────────

@router.callback_query(F.data == "s:cx")
async def cancel_wizard(callback: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(
        "❌ تم إلغاء عملية البحث.",
        reply_markup=get_back_button("main"),
    )
    await callback.answer()


# ─── Utility ──────────────────────────────────────────────────────────────

def _parse_iso_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
