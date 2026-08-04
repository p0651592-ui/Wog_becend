from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class WheelPlusRound(Base):
    __tablename__ = "wheel_plus_rounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    round_index: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="open", nullable=False)
    client_seed: Mapped[str] = mapped_column(String(128), default="wheel-plus-room", nullable=False)
    server_seed_hash: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    server_seed: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    nonce: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    winning_number: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    winning_color: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    lucky_numbers_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    result_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    total_bets: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_players: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_payout: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    bets = relationship("WheelPlusBet", back_populates="round", cascade="all, delete-orphan")


class WheelPlusBet(Base):
    __tablename__ = "wheel_plus_bets"
    __table_args__ = (
        UniqueConstraint("round_id", "user_id", "bet_cell", name="uq_wheel_plus_round_user_cell"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    round_id: Mapped[int] = mapped_column(
        ForeignKey("wheel_plus_rounds.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    bet_cell: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    payout: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_winner: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    round = relationship("WheelPlusRound", back_populates="bets")
