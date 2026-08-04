from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    first_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="user", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=func.now(), nullable=False
    )

    wallet = relationship("Wallet", back_populates="user", uselist=False, cascade="all, delete-orphan")
    stats = relationship("PlayerStats", back_populates="user", uselist=False, cascade="all, delete-orphan")


class Wallet(Base):
    __tablename__ = "wallets"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stars_balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=func.now(), nullable=False
    )

    user = relationship("User", back_populates="wallet")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    tx_type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_before: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    meta_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class PlayerStats(Base):
    __tablename__ = "player_stats"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    games_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_bet: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_win: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_loss: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    today_win: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    today_loss: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_volume: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_multiplier: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_win: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    last_game_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=func.now(), nullable=False
    )

    user = relationship("User", back_populates="stats")


class GameRound(Base):
    __tablename__ = "game_rounds"
    __table_args__ = (UniqueConstraint("user_id", "nonce", name="uq_round_user_nonce"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    game_type: Mapped[str] = mapped_column(String(64), nullable=False)
    bet: Mapped[int] = mapped_column(Integer, nullable=False)
    payout: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    multiplier: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    result_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    client_seed: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    server_seed_hash: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    server_seed: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    nonce: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    target_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    meta_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class WheelPlusRoom(Base):
    __tablename__ = "wheel_plus_rooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False, default="wheel_plus_room")
    title: Mapped[str] = mapped_column(String(128), default="Wheel Plus", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="betting", nullable=False)
    round_index: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    current_round_id: Mapped[int | None] = mapped_column(
        ForeignKey("wheel_plus_rounds.id", ondelete="SET NULL"), nullable=True
    )
    betting_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    betting_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=func.now(), nullable=False
    )


class WheelPlusRound(Base):
    __tablename__ = "wheel_plus_rounds"
    __table_args__ = (UniqueConstraint("room_id", "round_index", name="uq_wheel_plus_room_round_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("wheel_plus_rooms.id", ondelete="CASCADE"), index=True, nullable=False)
    round_index: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="betting", nullable=False)
    betting_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    betting_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    server_seed_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    server_seed: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    client_seed: Mapped[str] = mapped_column(String(128), default="wheel-plus-room", nullable=False)
    nonce: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    result_number: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    result_color: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    lucky_numbers_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    total_bet: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_payout: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=func.now(), nullable=False
    )


class WheelPlusBet(Base):
    __tablename__ = "wheel_plus_bets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("wheel_plus_rooms.id", ondelete="CASCADE"), index=True, nullable=False)
    round_id: Mapped[int] = mapped_column(ForeignKey("wheel_plus_rounds.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    cell_key: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=func.now(), nullable=False
    )
