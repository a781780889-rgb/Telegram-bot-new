from sqlalchemy import Column, BigInteger, String, DateTime, Enum, JSON, ForeignKey
from sqlalchemy.sql import func
from app.database.database import Base
import enum

class TaskStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TaskType(enum.Enum):
    SEARCH = "search"
    JOIN = "join"
    PUBLISH = "publish"

class Task(Base):
    __tablename__ = "tasks"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"))
    type = Column(Enum(TaskType))
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING)
    progress = Column(BigInteger, default=0)
    metadata_json = Column(JSON, nullable=True)
    error_log = Column(String, nullable=True)
    
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
