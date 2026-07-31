from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, Enum, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database.database import Base
import enum

class UserRole(enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MANAGER = "manager"
    USER = "user"

class User(Base):
    __tablename__ = "users"
    
    id = Column(BigInteger, primary_key=True, index=True)
    username = Column(String, nullable=True)
    full_name = Column(String, nullable=True)
    role = Column(Enum(UserRole), default=UserRole.USER)
    is_active = Column(Boolean, default=True)
    is_banned = Column(Boolean, default=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    accounts = relationship("Account", back_populates="owner")
    subscriptions = relationship("Subscription", back_populates="user")

class Account(Base):
    __tablename__ = "accounts"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"))
    phone = Column(String, unique=True)
    session_name = Column(String)           # legacy (اسم الملف القديم)
    session_string = Column(Text, nullable=True)  # StringSession مشفرة في DB
    is_connected = Column(Boolean, default=False)
    status = Column(String, default="active")
    last_check = Column(DateTime(timezone=True))
    
    owner = relationship("User", back_populates="accounts")
