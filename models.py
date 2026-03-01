"""
VocalGuard — Database Models
SQLAlchemy ORM with async SQLite for persisting session vitals.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Float, String, DateTime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = "sqlite+aiosqlite:///./vocalguard.db"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


class SessionLog(Base):
    """Stores every incoming biometric data packet for post-performance review."""

    __tablename__ = "session_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    heart_rate = Column(Integer, nullable=False)
    spo2 = Column(Integer, nullable=False)
    voice_stress_level = Column(Float, nullable=False)
    pitch = Column(Float, nullable=True, default=0.0)                    # Hz from mic
    volume = Column(Float, nullable=True, default=0.0)                   # dB from mic
    alert_level = Column(String, nullable=False, default="normal")       # normal | warning | critical
    alert_message = Column(String, nullable=True)
    timestamp = Column(String, nullable=False)                            # ISO-8601 from device
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return (
            f"<SessionLog id={self.id} hr={self.heart_rate} spo2={self.spo2} "
            f"pitch={self.pitch} vol={self.volume} alert={self.alert_level} ts={self.timestamp}>"
        )


async def init_db() -> None:
    """Create all tables if they don't exist yet."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
