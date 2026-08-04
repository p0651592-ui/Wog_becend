from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, desc, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from app.db.base import Base
from app.db.models import User
from app.db.session import get_db
from app.main import _ensure_user, app
from app.services.stats_service import StatsService
from app.services.wallet_service import WalletService

ROOM_NAME = "wheel_plus"
ROOM_LABEL = "Wheel Plus"
BETTING_WINDOW_SECONDS = 20
ROUND_HOLD_SECONDS = 4
HISTORY_LIMIT = 10

WHEEL_SEQUENCE = [
    "0", "28", "9", "26", "30", "11", "7", "20", "32", "17", "5", "22",
    "34", "15", "3", "24", "36", "13", "1", "00", "27", "10", "25", "29",
    "12", "8", "19", "31", "18", "6", "21", "33", "16", "4", "23", "35",
    "14", "2",
]
RED_NUMBERS = {"1", "3", "5", "7", "9", "12", "14", "16", "18", "19", "21", "23", "25", "27", "30", "32", "34", "36"}
BLACK_NUMBERS = {"2", "4", "6", "8", "10", "11", "13", "15", "17", "20", "22", "24", "26", "28", "29", "31", "33", "35"}
LUCKY_MULTIPLIERS = [50, 100, 300]
SUPPORTED_CELLS = {
    "red", "black", "even", "odd", "low", "high",
    "doz1", "doz2", "doz3", "column1", "column2", "column3",
    *{f"num{i}" for i in range(37)},
    "zero",
}


class WheelPlusRound(Base):
    __tablename__ = "wheel_plus_rounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_name: Mapped[str] = mapped_column(String(32), index=True, default=ROOM_NAME, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="betting", nullable=False)
    result_number: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    result_color: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    client_seed: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    server_seed: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    server_seed_hash: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    nonce: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    betting_close_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_bet: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_payout: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lucky_numbers_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    result_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, onupdate=lambda: datetime.now(timezone.utc)
    )

    bets = relationship("WheelPlusBet", back_populates="round", cascade="all, delete-orphan")


class WheelPlusBet(Base):
    __tablename__ = "wheel_plus_bets"
    __table_args__ = (
        UniqueConstraint("round_id", "user_id", "cell_key", name="uq_wheel_plus_round_user_cell"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("wheel_plus_rounds.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    cell_key: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    round = relationship("WheelPlusRound", back_populates="bets")


class WheelPlusInitPayload(BaseModel):
    init_data: str = Field(default="")


class WheelPlusBetPayload(BaseModel):
    init_data: str = Field(default="")
    cell_key: str = Field(default="")
    amount: int = Field(gt=0)


class WheelPlusRoundPayload(BaseModel):
    init_data: str = Field(default="")
    round_id: int = Field(gt=0)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash_seed(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _roulette_color(value: str) -> str:
    if value in {"0", "00"}:
        return "green"
    if value in RED_NUMBERS:
        return "red"
    if value in BLACK_NUMBERS:
        return "black"
    return "green"


def _generate_lucky_numbers() -> list[dict[str, int]]:
    available = list(range(37))
    lucky_numbers: list[dict[str, int]] = []
    for multiplier in LUCKY_MULTIPLIERS:
        index = secrets.randbelow(len(available))
        number = int(available.pop(index))
        lucky_numbers.append({"number": number, "multiplier": multiplier})
    return lucky_numbers


def _normalize_cell_key(cell_key: str) -> str:
    key = (cell_key or "").strip().lower()
    aliases = {
        "dozen1": "doz1",
        "dozen2": "doz2",
        "dozen3": "doz3",
        "column_1": "column1",
        "column_2": "column2",
        "column_3": "column3",
        "0": "num0",
    }
    return aliases.get(key, key)


def _is_black(number: int) -> bool:
    return str(number) in BLACK_NUMBERS


def _cell_multiplier(cell_key: str, result: str) -> int:
    key = _normalize_cell_key(cell_key)
    if key not in SUPPORTED_CELLS:
        return 0

    if key in {"num0", "zero"}:
        return 30 if result == "0" else 0
    if key.startswith("num") and key[3:].isdigit():
        return 30 if result == key[3:] else 0

    if key == "red":
        return 2 if result not in {"0", "00"} and not _is_black(int(result)) else 0
    if key == "black":
        return 2 if result not in {"0", "00"} and _is_black(int(result)) else 0
    if key == "even":
        return 2 if result not in {"0", "00"} and int(result) % 2 == 0 else 0
    if key == "odd":
        return 2 if result not in {"0", "00"} and int(result) % 2 == 1 else 0
    if key == "low":
        return 2 if result not in {"0", "00"} and 1 <= int(result) <= 18 else 0
    if key == "high":
        return 2 if result not in {"0", "00"} and 19 <= int(result) <= 36 else 0

    if key in {"doz1", "doz2", "doz3"}:
        if result in {"0", "00"}:
            return 0
        number = int(result)
        if key == "doz1" and 1 <= number <= 12:
            return 3
        if key == "doz2" and 13 <= number <= 24:
            return 3
        if key == "doz3" and 25 <= number <= 36:
            return 3

    if key in {"column1", "column2", "column3"}:
        if result in {"0", "00"}:
            return 0
        number = int(result)
        column = ((number - 1) % 3) + 1
        if (key == "column1" and column == 1) or (key == "column2" and column == 2) or (key == "column3" and column == 3):
            return 3

    return 0


def _render_lucky_numbers(lucky_numbers_json: str) -> list[dict[str, int]]:
    try:
        data = json.loads(lucky_numbers_json or "[]")
        return [
            {"number": int(item.get("number", 0)), "multiplier": int(item.get("multiplier", 0))}
            for item in data
        ]
    except Exception:
        return []


def _serialize_round(round_row: WheelPlusRound) -> dict[str, Any]:
    data = json.loads(round_row.result_json or "{}")
    return {
        "id": round_row.id,
        "status": round_row.status,
        "room": round_row.room_name,
        "result_number": round_row.result_number or data.get("result_number", ""),
        "result_color": round_row.result_color or data.get("result_color", ""),
        "server_seed_hash": round_row.server_seed_hash,
        "server_seed": round_row.server_seed,
        "client_seed": round_row.client_seed,
        "nonce": round_row.nonce,
        "lucky_numbers": _render_lucky_numbers(round_row.lucky_numbers_json),
        "total_bet": round_row.total_bet,
        "total_payout": round_row.total_payout,
        "betting_close_at": round_row.betting_close_at.isoformat(),
        "settled_at": round_row.settled_at.isoformat() if round_row.settled_at else None,
        "created_at": round_row.created_at.isoformat(),
    }


def _serialize_history_round(round_row: WheelPlusRound) -> dict[str, Any]:
    payload = _serialize_round(round_row)
    payload["result_json"] = json.loads(round_row.result_json or "{}")
    return payload


def _current_round_query() -> Any:
    return select(WheelPlusRound).where(WheelPlusRound.room_name == ROOM_NAME).order_by(desc(WheelPlusRound.id))


def _ensure_active_round(session: Session) -> WheelPlusRound:
    now = _utcnow()
    current = session.scalar(_current_round_query())
    if current is None:
        current = WheelPlusRound(
            room_name=ROOM_NAME,
            status="betting",
            client_seed="wheel-plus-room",
            server_seed=secrets.token_hex(32),
            server_seed_hash="",
            nonce=secrets.randbelow(1_000_000),
            betting_close_at=now + timedelta(seconds=BETTING_WINDOW_SECONDS),
            lucky_numbers_json=json.dumps(_generate_lucky_numbers(), ensure_ascii=False),
        )
        current.server_seed_hash = _hash_seed(current.server_seed)
        session.add(current)
        session.flush()
        return current

    if current.status == "betting" and now >= current.betting_close_at:
        _settle_round(session, current)
        session.flush()
        return _ensure_active_round(session)

    if current.status == "settled" and current.settled_at and now >= current.settled_at + timedelta(seconds=ROUND_HOLD_SECONDS):
        next_round = WheelPlusRound(
            room_name=ROOM_NAME,
            status="betting",
            client_seed="wheel-plus-room",
            server_seed=secrets.token_hex(32),
            server_seed_hash="",
            nonce=secrets.randbelow(1_000_000),
            betting_close_at=now + timedelta(seconds=BETTING_WINDOW_SECONDS),
            lucky_numbers_json=json.dumps(_generate_lucky_numbers(), ensure_ascii=False),
        )
        next_round.server_seed_hash = _hash_seed(next_round.server_seed)
        session.add(next_round)
        session.flush()
        return next_round

    return current


def _settle_round(session: Session, round_row: WheelPlusRound) -> WheelPlusRound:
    if round_row.status == "settled":
        return round_row

    result_number = secrets.choice(WHEEL_SEQUENCE)
    result_color = _roulette_color(result_number)
    bets = session.execute(select(WheelPlusBet).where(WheelPlusBet.round_id == round_row.id)).scalars().all()

    totals_by_user: dict[int, dict[str, int]] = {}
    winning_multiplier_by_user: dict[int, int] = {}
    total_payout = 0
    total_bet = 0

    for bet in bets:
        total_bet += bet.amount
        multiplier = _cell_multiplier(bet.cell_key, result_number)
        user_totals = totals_by_user.setdefault(bet.user_id, {"bet": 0, "payout": 0})
        user_totals["bet"] += bet.amount
        if multiplier > 0:
            payout = bet.amount * multiplier
            total_payout += payout
            user_totals["payout"] += payout
            winning_multiplier_by_user[bet.user_id] = max(winning_multiplier_by_user.get(bet.user_id, 0), multiplier)
            WalletService.payout(
                session,
                bet.user_id,
                payout,
                meta={"game": "wheel_plus", "round_id": round_row.id, "cell_key": bet.cell_key, "result": result_number},
            )

    for user_id, totals in totals_by_user.items():
        StatsService.update_after_round(
            session,
            user_id,
            bet=totals["bet"],
            payout=totals["payout"],
            multiplier=winning_multiplier_by_user.get(user_id, 0),
        )

    round_row.result_number = result_number
    round_row.result_color = result_color
    round_row.status = "settled"
    round_row.settled_at = _utcnow()
    round_row.total_bet = total_bet
    round_row.total_payout = total_payout
    round_row.result_json = json.dumps(
        {
            "result_number": result_number,
            "result_color": result_color,
            "lucky_numbers": _render_lucky_numbers(round_row.lucky_numbers_json),
            "server_seed_hash": round_row.server_seed_hash,
            "server_seed": round_row.server_seed,
            "client_seed": round_row.client_seed,
            "nonce": round_row.nonce,
            "total_bet": total_bet,
            "total_payout": total_payout,
        },
        ensure_ascii=False,
    )
    return round_row


def _load_live_players(session: Session, round_id: int) -> list[dict[str, Any]]:
    rows = session.execute(
        select(WheelPlusBet, User)
        .join(User, User.id == WheelPlusBet.user_id)
        .where(WheelPlusBet.round_id == round_id)
        .order_by(desc(WheelPlusBet.amount), desc(WheelPlusBet.created_at))
    ).all()

    grouped: dict[int, dict[str, Any]] = {}
    for bet, user in rows:
        item = grouped.setdefault(
            user.id,
            {
                "user_id": user.id,
                "telegram_id": user.telegram_id,
                "name": user.username or user.first_name or "noname",
                "status": user.status,
                "role": user.role,
                "amount": 0,
                "cells": [],
                "created_at": bet.created_at.isoformat(),
            },
        )
        item["amount"] += bet.amount
        if bet.cell_key not in item["cells"]:
            item["cells"].append(bet.cell_key)
        if bet.created_at.isoformat() < item["created_at"]:
            item["created_at"] = bet.created_at.isoformat()

    return list(grouped.values())


def _load_cell_totals(session: Session, round_id: int) -> dict[str, int]:
    rows = session.execute(
        select(WheelPlusBet.cell_key, func.coalesce(func.sum(WheelPlusBet.amount), 0))
        .where(WheelPlusBet.round_id == round_id)
        .group_by(WheelPlusBet.cell_key)
    ).all()
    return {str(cell_key): int(amount or 0) for cell_key, amount in rows}


def _load_history(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        select(WheelPlusRound)
        .where(WheelPlusRound.room_name == ROOM_NAME, WheelPlusRound.status == "settled")
        .order_by(desc(WheelPlusRound.id))
        .limit(HISTORY_LIMIT)
    ).scalars().all()
    return [_serialize_history_round(row) for row in rows]


def _build_room_payload(session: Session, user: User, round_row: WheelPlusRound, *, settled_round: WheelPlusRound | None = None) -> dict[str, Any]:
    profile = StatsService.build_profile_payload(session, user)
    profile["text"] = StatsService.format_profile_text(profile)
    snapshot = WalletService.get_snapshot(session, user.id)
    history = _load_history(session)
    live_players = _load_live_players(session, round_row.id) if round_row.status == "betting" else []
    cell_totals = _load_cell_totals(session, round_row.id) if round_row.status == "betting" else {}
    seconds_remaining = max(0, int((round_row.betting_close_at - _utcnow()).total_seconds())) if round_row.status == "betting" else 0

    response = {
        "status": "success",
        "room": {
            "name": ROOM_LABEL,
            "key": ROOM_NAME,
            "round_id": round_row.id,
            "status": round_row.status,
            "seconds_remaining": seconds_remaining,
            "total_bet": round_row.total_bet,
            "total_payout": round_row.total_payout,
            "players_count": len(live_players),
        },
        "round": _serialize_round(round_row),
        "balance": snapshot.balance,
        "profile": profile,
        "history": history,
        "live_players": live_players,
        "cell_totals": cell_totals,
    }
    if settled_round is not None:
        response["settled_round"] = _serialize_round(settled_round)
    return response


@app.post("/api/wheel-plus/state")
def wheel_plus_state(payload: WheelPlusInitPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = _ensure_user(db, payload.init_data)
    round_row = _ensure_active_round(db)
    if round_row.status == "betting" and _utcnow() >= round_row.betting_close_at:
        settled_round = _settle_round(db, round_row)
        db.flush()
        round_row = _ensure_active_round(db)
        db.commit()
        return _build_room_payload(db, user, round_row, settled_round=settled_round)

    db.commit()
    return _build_room_payload(db, user, round_row)


@app.post("/api/wheel-plus/bet")
def wheel_plus_bet(payload: WheelPlusBetPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = _ensure_user(db, payload.init_data)
    cell_key = _normalize_cell_key(payload.cell_key)
    if cell_key not in SUPPORTED_CELLS:
        raise HTTPException(status_code=400, detail="Unsupported bet cell")

    round_row = _ensure_active_round(db)
    if round_row.status != "betting" or _utcnow() >= round_row.betting_close_at:
        settled_round = _settle_round(db, round_row)
        db.flush()
        round_row = _ensure_active_round(db)
        db.commit()
        payload_data = _build_room_payload(db, user, round_row, settled_round=settled_round)
        payload_data["message"] = "Ставки уже закрыты, следующий раунд открыт."
        return payload_data

    snapshot = WalletService.place_bet(
        db,
        user.id,
        payload.amount,
        tx_type="wheel_plus_bet",
        meta={"game": "wheel_plus", "room": ROOM_NAME, "round_id": round_row.id, "cell_key": cell_key},
    )

    bet_row = db.scalar(
        select(WheelPlusBet).where(
            WheelPlusBet.round_id == round_row.id,
            WheelPlusBet.user_id == user.id,
            WheelPlusBet.cell_key == cell_key,
        ).with_for_update()
    )
    if bet_row is None:
        bet_row = WheelPlusBet(round_id=round_row.id, user_id=user.id, cell_key=cell_key, amount=payload.amount)
        db.add(bet_row)
    else:
        bet_row.amount += payload.amount

    round_row.total_bet += payload.amount
    db.commit()
    response = _build_room_payload(db, user, round_row)
    response["balance"] = snapshot.balance
    return response


@app.post("/api/wheel-plus/settle")
def wheel_plus_settle(payload: WheelPlusInitPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = _ensure_user(db, payload.init_data)
    round_row = _ensure_active_round(db)
    if round_row.status == "betting" and _utcnow() < round_row.betting_close_at:
        raise HTTPException(status_code=409, detail="Betting is still open")

    settled_round = round_row
    if round_row.status == "betting":
        settled_round = _settle_round(db, round_row)
    db.flush()
    next_round = _ensure_active_round(db)
    db.commit()
    return _build_room_payload(db, user, next_round, settled_round=settled_round)


@app.post("/api/wheel-plus/round")
def wheel_plus_round_details(payload: WheelPlusRoundPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    _ensure_user(db, payload.init_data)
    round_row = db.scalar(select(WheelPlusRound).where(WheelPlusRound.id == payload.round_id))
    if round_row is None:
        raise HTTPException(status_code=404, detail="Round not found")

    bets = db.execute(
        select(WheelPlusBet, User)
        .join(User, User.id == WheelPlusBet.user_id)
        .where(WheelPlusBet.round_id == round_row.id)
        .order_by(desc(WheelPlusBet.amount), desc(WheelPlusBet.created_at))
    ).all()

    return {
        "status": "success",
        "round": _serialize_round(round_row),
        "bets": [
            {
                "user_id": user.id,
                "telegram_id": user.telegram_id,
                "name": user.username or user.first_name or "noname",
                "cell_key": bet.cell_key,
                "amount": bet.amount,
                "created_at": bet.created_at.isoformat(),
            }
            for bet, user in bets
        ],
        "players": _load_live_players(db, round_row.id),
    }
