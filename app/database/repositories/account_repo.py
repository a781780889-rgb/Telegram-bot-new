from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database.models.user import Account


class AccountRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_phone(self, phone: str) -> Account | None:
        result = await self.db.execute(select(Account).where(Account.phone == phone))
        return result.scalar_one_or_none()

    async def get_by_id(self, account_id: int) -> Account | None:
        result = await self.db.execute(select(Account).where(Account.id == account_id))
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: int) -> list[Account]:
        result = await self.db.execute(select(Account).where(Account.user_id == user_id))
        return list(result.scalars().all())

    async def list_active_by_user(self, user_id: int) -> list[Account]:
        """Return only accounts with a valid session_string."""
        result = await self.db.execute(
            select(Account).where(
                Account.user_id == user_id,
                Account.is_connected == True,
                Account.status == "active",
                Account.session_string != None,
                Account.session_string != "",
            )
        )
        return list(result.scalars().all())

    async def create(
        self,
        user_id: int,
        phone: str,
        session_name: str,
        session_string: str | None = None,
    ) -> Account:
        account = Account(
            user_id=user_id,
            phone=phone,
            session_name=session_name,
            session_string=session_string,
            is_connected=True,
            status="active",
        )
        self.db.add(account)
        await self.db.commit()
        await self.db.refresh(account)
        return account

    async def update_session_string(self, account_id: int, session_string: str) -> None:
        account = await self.get_by_id(account_id)
        if account:
            account.session_string = session_string
            account.status = "active"
            account.is_connected = True
            account.last_check = datetime.now(timezone.utc)
            await self.db.commit()

    async def mark_disconnected(self, account_id: int, reason: str = "session_expired") -> None:
        account = await self.get_by_id(account_id)
        if account:
            account.is_connected = False
            account.status = reason
            account.last_check = datetime.now(timezone.utc)
            await self.db.commit()

    async def delete(self, account_id: int) -> None:
        account = await self.get_by_id(account_id)
        if account:
            await self.db.delete(account)
            await self.db.commit()
