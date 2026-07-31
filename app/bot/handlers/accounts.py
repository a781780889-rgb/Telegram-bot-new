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
        [InlineKeyboardButton(text="📊 إحصائيات", callback_data="accounts:stats")],
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
    except Exception as e:  # noqa: BLE001 - last-resort guard, never crash the handler
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
    except Exception as e:  # noqa: BLE001
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

    # Delete the message containing the password from the chat so it
    # doesn't linger in plain text in the conversation history.
    try:
        await message.delete()
    except Exception:  # noqa: BLE001 - best effort only, bot may lack delete rights
        pass

    try:
        await account_service.submit_password(user_id, password)
    except AccountServiceError as e:
        await message.answer(e.message, reply_markup=_cancel_only_keyboard())
        return
    except Exception as e:  # noqa: BLE001
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

    # Re-use start_login with the same phone; it internally enforces
    # FloodWait handling and won't fire duplicate requests recklessly.
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
        phone, session_name = await account_service.finalize(user_id)
    except AccountServiceError as e:
        await message.answer(e.message)
        await state.clear()
        return
    except Exception as e:  # noqa: BLE001
        logger.error(f"user={user_id} unexpected error finalizing login: {e}")
        await message.answer("⚠️ تم تسجيل الدخول لكن حدث خطأ أثناء حفظ الحساب. تواصل مع الدعم.")
        await state.clear()
        return

    async with AsyncSessionLocal() as db:
        repo = AccountRepository(db)
        existing = await repo.get_by_phone(phone)
        if existing is None:
            await repo.create(user_id=user_id, phone=phone, session_name=session_name)

    await state.clear()
    await message.answer(f"✅ تم تسجيل الدخول وحفظ الحساب بنجاح.\n📱 {phone}")
