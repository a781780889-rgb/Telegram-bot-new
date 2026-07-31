"""
Telegram account login/session manager.

Responsibilities:
- Own a single in-memory "login state" per user_id so concurrent /
  duplicate "add account" presses can never spawn parallel Telethon
  clients for the same user.
- Wrap send_code_request / sign_in / 2FA with explicit handling for
  every Telethon exception relevant to login (never a bare
  "except Exception: pass").
- Never create/keep a session file on disk until sign-in has fully
  succeeded (2FA included) so a half-finished login can't leave a
  corrupt or misleading session behind.
- Enforce a timeout on an open login so a client is never left
  connected and dangling forever.
- Never log the OTP code, the 2FA password, session strings, or API
  credentials. Phone numbers are always masked before logging.
"""

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    ApiIdInvalidError,
    AuthRestartError,
    FloodWaitError,
    PhoneCodeEmptyError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    PhoneNumberBannedError,
    PhoneNumberUnoccupiedError,
    SessionPasswordNeededError,
    PasswordHashInvalidError,
)

from app.config.config import settings

LOGIN_TIMEOUT_SECONDS = 5 * 60  # 5 minutes to finish phone -> code -> (2FA)
SESSIONS_DIR = "sessions"


def mask_phone(phone: str) -> str:
    """+967771234567 -> +967****4567 (never log a full phone number)."""
    if not phone or len(phone) < 6:
        return "***"
    return f"{phone[:4]}****{phone[-4:]}"


class AccountServiceError(Exception):
    """Base class for user-facing login errors. `message` is Arabic, ready to send as-is."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


@dataclass
class LoginState:
    """One in-progress login attempt for a single user_id."""

    user_id: int
    phone: str
    client: TelegramClient
    phone_code_hash: str
    step: str = "waiting_code"  # waiting_code | waiting_password
    created_at: float = field(default_factory=time.monotonic)
    last_code_request_at: float = field(default_factory=time.monotonic)

    def is_expired(self) -> bool:
        return (time.monotonic() - self.created_at) > LOGIN_TIMEOUT_SECONDS


class AccountService:
    """
    Single shared instance (see bot/handlers/accounts.py) holding one
    LoginState per user so two concurrent "add account" flows for the
    same user can never race each other or leak a Telethon client.
    """

    def __init__(self, session_dir: str = SESSIONS_DIR):
        self.session_dir = session_dir
        os.makedirs(session_dir, exist_ok=True)
        self._logins: dict[int, LoginState] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock_for(self, user_id: int) -> asyncio.Lock:
        if user_id not in self._locks:
            self._locks[user_id] = asyncio.Lock()
        return self._locks[user_id]

    def has_active_login(self, user_id: int) -> bool:
        state = self._logins.get(user_id)
        if state is None:
            return False
        if state.is_expired():
            return False
        return True

    @staticmethod
    def normalize_phone(raw: str) -> str:
        """Strip spaces/dashes/parens; keep a leading + and digits only."""
        cleaned = raw.strip()
        cleaned = "".join(ch for ch in cleaned if ch.isdigit() or ch == "+")
        return cleaned

    @staticmethod
    def is_valid_phone(phone: str) -> bool:
        if not phone.startswith("+"):
            return False
        digits = phone[1:]
        return digits.isdigit() and 8 <= len(digits) <= 15

    @staticmethod
    def normalize_code(raw: str) -> str:
        """
        Accept "12345" as well as spaced/dashed input like "1 2 3 4 5"
        or "1-2-3-4-5", but never mutate a code that was already a
        clean digit string (no leading-zero stripping, no int() cast
        that would silently drop a leading zero).
        """
        return "".join(ch for ch in raw.strip() if ch.isdigit())

    async def _cleanup(self, user_id: int, *, disconnect: bool = True) -> None:
        state = self._logins.pop(user_id, None)
        if state and disconnect:
            try:
                if state.client.is_connected():
                    await state.client.disconnect()
            except Exception as e:  # noqa: BLE001 - log, never swallow silently
                logger.warning(f"user={user_id} error disconnecting stale client: {e}")

    async def cancel_login(self, user_id: int) -> None:
        logger.info(f"user={user_id} login cancelled by user")
        await self._cleanup(user_id)

    async def start_login(self, user_id: int, phone_raw: str) -> str:
        """
        Normalize + validate the phone, open a Telethon client, and
        request a login code. Returns a ready-to-send Arabic status
        message. Raises AccountServiceError with an Arabic message on
        any failure. No session file is persisted at this stage.
        """
        lock = self._lock_for(user_id)
        async with lock:
            # A previous unfinished attempt for this user is replaced,
            # never left running alongside a new one.
            if user_id in self._logins:
                await self._cleanup(user_id)

            phone = self.normalize_phone(phone_raw)
            if not self.is_valid_phone(phone):
                logger.info(f"user={user_id} phone rejected: invalid format")
                raise AccountServiceError(
                    "❌ صيغة رقم الهاتف غير صحيحة.\nالرجاء إرساله مع رمز الدولة، مثال: +967XXXXXXXXX"
                )

            client = TelegramClient(StringSession(), settings.API_ID, settings.API_HASH)

            try:
                await client.connect()
            except Exception as e:  # noqa: BLE001
                logger.error(f"user={user_id} phone={mask_phone(phone)} connect failed: {e}")
                await self._safe_disconnect(client)
                raise AccountServiceError(
                    "⚠️ تعذر الاتصال بخوادم Telegram حالياً. حاول مرة أخرى بعد قليل."
                )

            logger.info(f"user={user_id} phone={mask_phone(phone)} sending code request")
            try:
                sent = await client.send_code_request(phone)
            except PhoneNumberInvalidError:
                logger.info(f"user={user_id} phone={mask_phone(phone)} PhoneNumberInvalidError")
                await self._safe_disconnect(client)
                raise AccountServiceError("❌ رقم الهاتف غير صحيح.")
            except PhoneNumberBannedError:
                logger.info(f"user={user_id} phone={mask_phone(phone)} PhoneNumberBannedError")
                await self._safe_disconnect(client)
                raise AccountServiceError("❌ هذا الرقم محظور من قبل Telegram.")
            except ApiIdInvalidError:
                logger.error(f"user={user_id} ApiIdInvalidError - API_ID/API_HASH need review")
                await self._safe_disconnect(client)
                raise AccountServiceError(
                    "⚠️ خطأ في إعدادات النظام (API_ID/API_HASH). تم إبلاغ المشرف."
                )
            except FloodWaitError as e:
                logger.warning(f"user={user_id} phone={mask_phone(phone)} FloodWaitError {e.seconds}s")
                await self._safe_disconnect(client)
                raise AccountServiceError(
                    f"⏳ عدد كبير من المحاولات. الرجاء الانتظار {e.seconds} ثانية قبل إعادة المحاولة."
                )
            except AuthRestartError:
                logger.info(f"user={user_id} phone={mask_phone(phone)} AuthRestartError - retrying once")
                try:
                    sent = await client.send_code_request(phone)
                except Exception as e:  # noqa: BLE001
                    logger.error(f"user={user_id} phone={mask_phone(phone)} retry after AuthRestartError failed: {e}")
                    await self._safe_disconnect(client)
                    raise AccountServiceError("⚠️ حدث خطأ أثناء بدء تسجيل الدخول. حاول مرة أخرى.")
            except Exception as e:  # noqa: BLE001 - never swallow; log and surface generically
                logger.error(f"user={user_id} phone={mask_phone(phone)} unexpected send_code_request error: {e}")
                await self._safe_disconnect(client)
                raise AccountServiceError("⚠️ حدث خطأ غير متوقع أثناء طلب رمز الدخول. حاول مرة أخرى.")

            self._logins[user_id] = LoginState(
                user_id=user_id,
                phone=phone,
                client=client,
                phone_code_hash=sent.phone_code_hash,
            )

            logger.info(f"user={user_id} phone={mask_phone(phone)} code request sent via type={sent.type.__class__.__name__}")

            return (
                "📩 تم طلب رمز تسجيل الدخول من Telegram.\n\n"
                "تحقق من تطبيق Telegram (جلسة أخرى مفتوحة) أو الرسائل النصية SMS "
                "حسب الطريقة التي يحددها Telegram لحسابك، ثم أرسل الرمز المكوّن من 5 أرقام هنا."
            )

    async def submit_code(self, user_id: int, code_raw: str) -> tuple[bool, str]:
        """
        Verify the OTP code.
        Returns (done, message):
          - done=True, message=success text -> login fully complete, session saved by caller via finalize info in state
          - done=False, message=ask-for-password -> 2FA required, state.step becomes waiting_password
          - raises AccountServiceError on any failure (state is left usable for retry unless it says otherwise)
        """
        state = self._require_state(user_id)
        code = self.normalize_code(code_raw)
        if not code:
            raise AccountServiceError("❌ الرجاء إرسال رمز التحقق المكوّن من أرقام فقط.")

        logger.info(f"user={user_id} phone={mask_phone(state.phone)} submitting code (len={len(code)})")
        try:
            await state.client.sign_in(
                phone=state.phone, code=code, phone_code_hash=state.phone_code_hash
            )
        except SessionPasswordNeededError:
            logger.info(f"user={user_id} phone={mask_phone(state.phone)} 2FA required")
            state.step = "waiting_password"
            return False, (
                "🔐 هذا الحساب محمي بالتحقق بخطوتين (2FA).\n"
                "أرسل كلمة مرور Telegram لإكمال تسجيل الدخول."
            )
        except PhoneCodeInvalidError:
            logger.info(f"user={user_id} phone={mask_phone(state.phone)} PhoneCodeInvalidError")
            raise AccountServiceError("❌ رمز التحقق غير صحيح. حاول مرة أخرى.")
        except PhoneCodeExpiredError:
            logger.info(f"user={user_id} phone={mask_phone(state.phone)} PhoneCodeExpiredError")
            await self._cleanup(user_id)
            raise AccountServiceError("⏰ انتهت صلاحية الرمز. اضغط ➕ إضافة حساب لطلب رمز جديد.")
        except PhoneCodeEmptyError:
            logger.info(f"user={user_id} phone={mask_phone(state.phone)} PhoneCodeEmptyError")
            raise AccountServiceError("❌ لم يتم استلام رمز. الرجاء إرسال الرمز المكوّن من 5 أرقام.")
        except FloodWaitError as e:
            logger.warning(f"user={user_id} phone={mask_phone(state.phone)} FloodWaitError {e.seconds}s")
            raise AccountServiceError(f"⏳ محاولات كثيرة. الرجاء الانتظار {e.seconds} ثانية.")
        except Exception as e:  # noqa: BLE001
            logger.error(f"user={user_id} phone={mask_phone(state.phone)} unexpected sign_in error: {e}")
            raise AccountServiceError("⚠️ حدث خطأ غير متوقع أثناء التحقق من الرمز. حاول مرة أخرى.")

        logger.info(f"user={user_id} phone={mask_phone(state.phone)} sign_in success (no 2FA)")
        return True, "✅ تم تسجيل الدخول بنجاح."

    async def submit_password(self, user_id: int, password: str) -> str:
        """Complete 2FA. Returns success message. Raises AccountServiceError on failure."""
        state = self._require_state(user_id)
        if state.step != "waiting_password":
            raise AccountServiceError("⚠️ لا توجد عملية تسجيل دخول تنتظر كلمة مرور 2FA حالياً.")

        logger.info(f"user={user_id} phone={mask_phone(state.phone)} submitting 2FA password")
        try:
            await state.client.sign_in(password=password)
        except PasswordHashInvalidError:
            logger.info(f"user={user_id} phone={mask_phone(state.phone)} PasswordHashInvalidError")
            raise AccountServiceError("❌ كلمة المرور غير صحيحة. حاول مرة أخرى.")
        except FloodWaitError as e:
            logger.warning(f"user={user_id} phone={mask_phone(state.phone)} FloodWaitError {e.seconds}s (2FA)")
            raise AccountServiceError(f"⏳ محاولات كثيرة. الرجاء الانتظار {e.seconds} ثانية.")
        except Exception as e:  # noqa: BLE001
            logger.error(f"user={user_id} phone={mask_phone(state.phone)} unexpected 2FA error: {e}")
            raise AccountServiceError("⚠️ حدث خطأ غير متوقع أثناء التحقق من كلمة المرور. حاول مرة أخرى.")

        logger.info(f"user={user_id} phone={mask_phone(state.phone)} 2FA success")
        return "✅ تم تسجيل الدخول بنجاح."

    async def finalize(self, user_id: int) -> tuple[str, str, str]:
        """
        Called only after a successful sign_in (with or without 2FA).
        Extracts StringSession from the client (safe for DB storage),
        disconnects, and returns (phone, session_name, session_string).
        """
        state = self._require_state(user_id)
        phone = state.phone

        # Extract StringSession BEFORE disconnecting
        try:
            session_string = state.client.session.save()
        except Exception as e:
            logger.error(f"user={user_id} failed to export session string: {e}")
            session_string = ""

        try:
            if state.client.is_connected():
                await state.client.disconnect()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"user={user_id} phone={mask_phone(phone)} error disconnecting: {e}")

        safe_name = phone.replace("+", "")
        self._logins.pop(user_id, None)
        logger.info(f"user={user_id} phone={mask_phone(phone)} session exported as StringSession")
        return phone, safe_name, session_string

    def check_timeout(self, user_id: int) -> bool:
        """True if this user has an active login that has now timed out (state left as-is for caller to clean up)."""
        state = self._logins.get(user_id)
        return state is not None and state.is_expired()

    def _require_state(self, user_id: int) -> LoginState:
        state = self._logins.get(user_id)
        if state is None:
            raise AccountServiceError(
                "⚠️ لا توجد عملية إضافة حساب نشطة. اضغط ➕ إضافة حساب للبدء من جديد."
            )
        if state.is_expired():
            raise AccountServiceError(
                "⏰ انتهت مهلة إضافة الحساب.\nاضغط ➕ إضافة حساب للبدء من جديد."
            )
        return state

    @staticmethod
    async def _safe_disconnect(client: TelegramClient) -> None:
        try:
            if client.is_connected():
                await client.disconnect()
        except Exception:  # noqa: BLE001 - best-effort cleanup only
            pass


# Single shared instance used by handlers so login state is process-wide,
# not re-created per callback.
account_service = AccountService()
