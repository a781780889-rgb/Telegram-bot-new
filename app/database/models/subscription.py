from sqlalchemy import Column, BigInteger, String, DateTime, Enum, ForeignKey, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database.database import Base
import enum

class Plan(Base):
    __tablename__ = "plans"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String)
    price = Column(Float)
    duration_days = Column(BigInteger)
    max_accounts = Column(BigInteger)
    features = Column(String)

class Subscription(Base):
    __tablename__ = "subscriptions"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"))
    plan_id = Column(BigInteger, ForeignKey("plans.id"))
    status = Column(String, default="active")
    
    start_date = Column(DateTime(timezone=True), server_default=func.now())
    end_date = Column(DateTime(timezone=True))
    
    user = relationship("User", back_populates="subscriptions")
