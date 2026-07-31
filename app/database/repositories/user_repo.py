from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database.models.user import User, UserRole

class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: int) -> User:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def create(self, user_id: int, username: str, full_name: str, role: UserRole = UserRole.USER) -> User:
        user = User(id=user_id, username=username, full_name=full_name, role=role)
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def update_role(self, user_id: int, role: UserRole):
        user = await self.get_by_id(user_id)
        if user:
            user.role = role
            await self.db.commit()
        return user
