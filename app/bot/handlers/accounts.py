from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from loguru import logger

from app.bot.keyboards.main_menu import get_back_button
from app.bot.states.states import RegistrationStates
from app.database.database import AsyncSessionLocal
from app.database.repositories.account_repo import AccountRepository
from app.services.accounts.account_service import account_service, AccountServiceError

router = Router()


def _otp_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 إعادة إرسال الرمز", callback_data="accounts:resend")],
            [InlineKeyboardButton(text="❌ إلغاء", callback_data="accounts:cancel")],
        ]
    )


def _cancel_only_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ إلغاء", callback_data="accounts:cancel")]]
    )


@router.callback_query(F.data == "menu:accounts")
async def accounts_menu(callback: types.CallbackQuery):
    buttons = [
        [InlineKeyboardButton(text="➕ إضافة حساب", callback_data="accounts:add")],
        [InlineKeyboardButton(text="📋 حساباتي", callback_data="accounts:list")],
        [InlineKeyboardButton(text="🔍 فحص الحسابات", callback_data="accounts:check_all")],
        [InlineKeyboardButton(text="⬅️ رجوع", callback_data="back:main")],
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text("📂 إدارة الحسابات\n\nاختر من القائمة أدناه:", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "accounts:add")
async def add_account(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id

    if account_service.has_active_login(user_id):
        await callback.answer(
            "⚠️ توجد بالفعل عملية إضافة حساب نشطة. أكملها أو ألغِها أولاً.",
            show_alert=True,
        )
        return

    await state.set_state(RegistrationStates.WAITING_FOR_PHONE)
    await callback.message.edit_text(
        "➕ إضافة حساب جديد\n\nالرجاء إدخال رقم الهاتف مع رمز الدولة (مثال: +966500000000):",
        reply_markup=get_back_button("accounts"),
    )
    await callback.answer()


@router.message(RegistrationStates.WAITING_FOR_PHONE)
async def process_phone(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    phone_raw = message.text or ""

    status_msg = await message.answer("⏳ جاري الاتصال بـ Telegram وطلب رمز الدخول...")

    try:
        reply_text = await account_service.start_login(user_id, phone_raw)
    except AccountServiceError as e:
        await status_msg.edit_text(e.message)
        return
    except Exception as e:
        logger.error(f"user={user_id} unexpected error in process_phone: {e}")
        await status_msg.edit_text("⚠️ حدث خطأ غير متوقع. حاول مرة أخرى لاحقاً.")
        await state.clear()
        return

    await state.set_state(RegistrationStates.WAITING_FOR_OTP)
    await status_msg.edit_text(reply_text, reply_markup=_otp_keyboard())


@router.message(RegistrationStates.WAITING_FOR_OTP)
async def process_otp(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    code_raw = message.text or ""

    try:
        done, reply_text = await account_service.submit_code(user_id, code_raw)
    except AccountServiceError as e:
        await message.answer(e.message, reply_markup=_otp_keyboard())
        if "انتهت صلاحية" in e.message or "لا توجد عملية" in e.message:
            await state.clear()
        return
    except Exception as e:
        logger.error(f"user={user_id} unexpected error in process_otp: {e}")
        await message.answer("⚠️ حدث خطأ غير متوقع أثناء التحقق من الرمز. حاول مرة أخرى.", reply_markup=_otp_keyboard())
        return

    if not done:
        await state.set_state(RegistrationStates.WAITING_FOR_2FA)
        await message.answer(reply_text, reply_markup=_cancel_only_keyboard())
        return

    await _finish_login(message, state, user_id)


@router.message(RegistrationStates.WAITING_FOR_2FA)
async def process_2fa(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    password = message.text or ""

    try:
        await message.delete()
    except Exception:
        pass

    try:
        await account_service.submit_password(user_id, password)
    except AccountServiceError as e:
        await message.answer(e.message, reply_markup=_cancel_only_keyboard())
        return
    except Exception as e:
        logger.error(f"user={user_id} unexpected error in process_2fa: {e}")
        await message.answer("⚠️ حدث خطأ غير متوقع أثناء التحقق من كلمة المرور. حاول مرة أخرى.")
        return

    await _finish_login(message, state, user_id)


@router.callback_query(F.data == "accounts:resend")
async def resend_code(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    current_state = await state.get_data()
    phone = current_state.get("phone")

    if not account_service.has_active_login(user_id):
        await callback.answer("⚠️ لا توجد عملية نشطة لإعادة إرسال الرمز إليها.", show_alert=True)
        return

    try:
        reply_text = await account_service.start_login(user_id, phone or "")
    except AccountServiceError as e:
        await callback.answer(e.message, show_alert=True)
        return

    await callback.message.edit_text(reply_text, reply_markup=_otp_keyboard())
    await callback.answer("تم إرسال الطلب مجدداً")


@router.callback_query(F.data == "accounts:cancel")
async def cancel_login(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    await account_service.cancel_login(user_id)
    await state.clear()
    await callback.message.edit_text("❌ تم إلغاء عملية إضافة الحساب.", reply_markup=get_back_button("accounts"))
    await callback.answer()


async def _finish_login(message: types.Message, state: FSMContext, user_id: int) -> None:
    try:
        phone, session_name, session_string = await account_service.finalize(user_id)
    except AccountServiceError as e:
        await message.answer(e.message)
        await state.clear()
        return
    except Exception as e:
        logger.error(f"user={user_id} unexpected error finalizing login: {e}")
        await message.answer("⚠️ تم تسجيل الدخول لكن حدث خطأ أثناء حفظ الحساب. تواصل مع الدعم.")
        await state.clear()
        return

    async with AsyncSessionLocal() as db:
        repo = AccountRepository(db)
        existing = await repo.get_by_phone(phone)
        if existing is None:
            await repo.create(
                user_id=user_id,
                phone=phone,
                session_name=session_name,
                session_string=session_string,
            )
        else:
            await repo.update_session_string(existing.id, session_string)

    await state.clear()
    session_ok = "✅" if session_string else "⚠️ (session فارغة!)"
    await message.answer(
        f"✅ تم تسجيل الدخول وحفظ الحساب بنجاح.\n"
        f"📱 {phone}\n"
        f"🔑 Session: {session_ok}"
    )


# ── قائمة الحسابات ─────────────────────────────────────────────────────────
@router.callback_query(F.data == "accounts:list")
async def list_accounts(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    async with AsyncSessionLocal() as db:
        repo = AccountRepository(db)
        accounts = await repo.list_by_user(user_id)

    if not accounts:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ إضافة حساب", callback_data="accounts:add")],
            [InlineKeyboardButton(text="⬅️ رجوع", callback_data="menu:accounts")],
        ])
        await callback.message.edit_text("📋 لا توجد حسابات مضافة بعد.", reply_markup=kb)
        await callback.answer()
        return

    lines = ["📋 حساباتي\n━━━━━━━━━━━━━━━━━━"]
    buttons = []
    for acc in accounts:
        has_session = bool(acc.session_string)
        is_active = acc.status == "active" and acc.is_connected and has_session
        icon = "✅" if is_active else "⚠️" if not has_session else "❌"
        label = "نشط" if is_active else "يحتاج إعادة تسجيل" if not has_session else "غير نشط"
        lines.append(f"{icon} {acc.phone} — {label}")
        buttons.append([
            InlineKeyboardButton(
                text=f"{icon} {acc.phone}",
                callback_data=f"accounts:detail:{acc.id}"
            )
        ])

    buttons.append([InlineKeyboardButton(text="⬅️ رجوع", callback_data="menu:accounts")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text("\n".join(lines), reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("accounts:detail:"))
async def account_detail(callback: types.CallbackQuery):
    acc_id = int(callback.data.split(":")[-1])
    async with AsyncSessionLocal() as db:
        repo = AccountRepository(db)
        acc = await repo.get_by_id(acc_id)

    if not acc:
        await callback.answer("⚠️ الحساب غير موجود", show_alert=True)
        return

    has_session = bool(acc.session_string)
    is_connected = acc.is_connected and has_session
    status_text = "✅ نشط ومتصل" if is_connected else ("⚠️ يحتاج إعادة تسجيل دخول" if not has_session else "❌ غير نشط")
    session_status = "✅ محفوظة" if has_session else "❌ مفقودة — يجب إعادة تسجيل الدخول"

    text = (
        f"📱 تفاصيل الحساب\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📞 الرقم:    {acc.phone}\n"
        f"📊 الحالة:   {status_text}\n"
        f"🔑 Session:  {session_status}\n"
        f"🔗 متصل:     {'نعم' if acc.is_connected else 'لا'}\n"
    )

    buttons = []
    if not has_session or not acc.is_connected:
        buttons.append([
            InlineKeyboardButton(
                text="🔄 إعادة تسجيل الدخول",
                callback_data=f"accounts:relogin:{acc_id}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="🗑️ حذف الحساب", callback_data=f"accounts:delete:{acc_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ رجوع", callback_data="accounts:list")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("accounts:relogin:"))
async def relogin_account(callback: types.CallbackQuery, state: FSMContext):
    """Re-authenticate an existing account (refreshes session_string in DB)."""
    acc_id = int(callback.data.split(":")[-1])
    async with AsyncSessionLocal() as db:
        repo = AccountRepository(db)
        acc = await repo.get_by_id(acc_id)

    if not acc:
        await callback.answer("⚠️ الحساب غير موجود", show_alert=True)
        return

    # Store the account_id in FSM so _finish_login can update instead of create
    await state.set_state(RegistrationStates.WAITING_FOR_PHONE)
    await callback.message.edit_text(
        f"🔄 إعادة تسجيل دخول للحساب: {acc.phone}\n\n"
        "أدخل رقم الهاتف للمتابعة:",
        reply_markup=get_back_button("accounts"),
    )
    await callback.answer()


@router.callback_query(F.data == "accounts:check_all")
async def check_all_accounts(callback: types.CallbackQuery):
    """Quick session check for all accounts."""
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from app.config.config import settings as cfg

    user_id = callback.from_user.id
    await callback.message.edit_text("🔍 جاري فحص الحسابات...")

    async with AsyncSessionLocal() as db:
        repo = AccountRepository(db)
        accounts = await repo.list_by_user(user_id)

    if not accounts:
        await callback.message.edit_text(
            "📋 لا توجد حسابات.",
            reply_markup=get_back_button("accounts")
        )
        await callback.answer()
        return

    results = []
    async with AsyncSessionLocal() as db:
        repo = AccountRepository(db)
        for acc in accounts:
            if not acc.session_string:
                results.append(f"⚠️ {acc.phone} — session مفقودة")
                await repo.mark_disconnected(acc.id, "no_session")
                continue
            client = TelegramClient(
                StringSession(acc.session_string),
                cfg.API_ID,
                cfg.API_HASH,
            )
            try:
                await client.connect()
                authorized = await client.is_user_authorized()
                await client.disconnect()
                if authorized:
                    await repo.update_session_string(acc.id, acc.session_string)
                    results.append(f"✅ {acc.phone} — نشط")
                else:
                    await repo.mark_disconnected(acc.id, "session_expired")
                    results.append(f"❌ {acc.phone} — session منتهية")
            except Exception as e:
                results.append(f"❌ {acc.phone} — خطأ: {str(e)[:50]}")
                await repo.mark_disconnected(acc.id, "error")

    text = "🔍 نتائج الفحص:\n━━━━━━━━━━━━━━\n" + "\n".join(results)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 قائمة الحسابات", callback_data="accounts:list")],
        [InlineKeyboardButton(text="⬅️ رجوع", callback_data="menu:accounts")],
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("accounts:delete:"))
async def delete_account(callback: types.CallbackQuery):
    acc_id = int(callback.data.split(":")[-1])
    async with AsyncSessionLocal() as db:
        repo = AccountRepository(db)
        await repo.delete(acc_id)
    await callback.answer("✅ تم حذف الحساب", show_alert=True)
    await list_accounts(callback)
