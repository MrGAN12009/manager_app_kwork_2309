from __future__ import annotations
import os
from datetime import datetime
from typing import Optional

from sqlalchemy import create_engine, String, Integer, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker, scoped_session


class Base(DeclarativeBase):
    pass


def get_database_url() -> str:
    return os.getenv("MANAGER_DATABASE_URL", "sqlite:///manager.db")


engine = create_engine(get_database_url(), echo=False, future=True)
SessionLocal = scoped_session(sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False))


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Bot(Base):
    __tablename__ = "bots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    token: Mapped[str] = mapped_column(String(255), nullable=False)
    repo_url: Mapped[str] = mapped_column(String(512), nullable=False)
    branch: Mapped[str] = mapped_column(String(128), default="master")
    workdir: Mapped[str] = mapped_column(String(1024), nullable=False)

    env_text: Mapped[str] = mapped_column(Text, default="")
    db_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(32), default="stopped")  # running/stopped/errored/setting_up
    process_pid: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    last_commit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_stopped_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    log_path: Mapped[str] = mapped_column(String(1024), default="")
    venv_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    setup_status: Mapped[str] = mapped_column(String(32), default="pending")  # pending/running/done/failed
    setup_step: Mapped[int] = mapped_column(Integer, default=0)
    setup_total: Mapped[int] = mapped_column(Integer, default=0)
    setup_message: Mapped[str] = mapped_column(String(512), default="")

    stats: Mapped["BotStats"] = relationship("BotStats", back_populates="bot", uselist=False, cascade="all, delete-orphan")


class BotStats(Base):
    __tablename__ = "bot_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), unique=True)

    messages_count: Mapped[int] = mapped_column(Integer, default=0)
    users_count: Mapped[int] = mapped_column(Integer, default=0)
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    bot: Mapped[Bot] = relationship("Bot", back_populates="stats")


class BotMessage(Base):
    __tablename__ = "bot_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), index=True, nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, index=True, nullable=True)
    chat_id: Mapped[Optional[int]] = mapped_column(Integer, index=True, nullable=True)
    message_type: Mapped[str] = mapped_column(String(32), default="text")
    text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
