from __future__ import annotations

import json
import secrets
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.schemas import InitDataPayload
from app.db.models import GameRound, PlayerStats, User, Wallet, WheelPlusBet, WheelPlusRoom, WheelPlusRound
from app.server import AMERICAN_WHEEL_SEQUENCE, BLACK_NUMBERS, RED_NUMBERS, app, _ensure_user
from app.db.session import get_db
from app.services.stats_service import StatsService
from app.services.wallet_service import WalletService

WHEEL_PLUS_SEQUENCE = [
    "0", "32", "15", "19", "4", "21", "2", "25", "17", "34", "6", "27",
    "13", "36", "11", "30", "8", "23", "10", "5", "24", "16", "33", "1",
    "20", "14", "31", "9", "22", "18", "29", "7", "28", "12", "35", "3", "26",
]

WHEEL_PLUS_BETTING_SECONDS = 25
WHEEL_PLUS_SETTLED_SECONDS = 4


class WheelPlusBetPayload(BaseModel):
    init_data: str = Field(default="")
    cell_key: str = Field(default="")
    amount: int = Field(gt=0)


class WheelPlusRoomPayload(BaseModel):
    init_data: str = Field(default="")


class WheelPlusSettlePayload(BaseModel):
    init_data: str = Field(default="")


CELL_LABELS = {
    "red": "Красное",
    "black": "Чёрное",
    "even": "Чёт",
    "odd": "Нечёт",
    "low": "1–18",
    "high": "19–36",
    "doz1": "1-я дюжина",
    "doz2": "2-я дюжина",
    "doz3": "3-я дюжина",
    "column1": "1-й столбец",
    "column2": "2-й столбец",
    "column3": "3-й столбец",
    "zero": "0",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_cell_key(cell_key: str) -> str:
    key = str(cell_key or "").strip().lower()
    if key in {"dozen1", "dozen_1"}:
        return "doz1"
    if key in {"dozen2", "dozen_2"}:
        return "doz2"
    if key in {"dozen3", "dozen_3"}:
        return "doz3"
    if key in {"num0", "num00", "0", "zero"}:
        return "zero"
    return key


def _room_key() -> str:
    return "wheel_plus_room"


def _build_lucky_numbers(result_number: str, room_round_index: int) -> list[dict[str, Any]]:
    try:
        idx = WHEEL_PLUS_SEQUENCE.index(str(result_number))
    except ValueError:
        idx = 0
    picks = [
        WHEEL_PLUS_SEQUENCE[idx],
        WHEEL_PLUS_SEQUENCE[(idx + 7 + room_round_index) % len(WHEEL_PLUS_SEQUENCE)],
        WHEEL_PLUS_SEQUENCE[(idx + 15 + room_round_index * 2) % len(WHEEL_PLUS_SEQUENCE)],
    ]
    multipliers = [50, 100, 300]
    return [{"number": number, "multiplier": multipliers[i]} for i, number in enumerate(picks)]


def _wheel_color(value: str) -> str:
    value = str(value)
    if value == "0":
        return "green"
    if value in RED_NUMBERS:
        return "red"
    if value in BLACK_NUMBERS:
        return "black"
    return "black"


def _cell_multiplier(cell_key: str, result_number: str) -> int:
    key = _normalize_cell_key(cell_key)
    result = str(result_number)

    if key in {f"num{i}" for i in range(37)}:
        return 30 if key == f"num{result}" else 0
    if key == "zero":
        return 30 if result == "0" else 0
    if key == "red":
        return 2 if result in RED_NUMBERS else 0
    if key == "black":
        return 2 if result in BLACK_NUMBERS else 0
    if key == "even":
        return 2 if result.isdigit() and int(result) % 2 == 0 and result != "0" else 0
    if key == "odd":
        return 2 if result.isdigit() and int(result) % 2 == 1 else 0
    if key == "low":
        return 2 if result.isdigit() and 1 <= int(result) <= 18 else 0
    if key == "high":
        return 2 if result.isdigit() and 19 <= int(result) <= 36 else 0
    if key == "doz1":
        return 3 if result.isdigit() and 1 <= int(result) <= 12 else 0
    if key == "doz2":
        return 3 if result.isdigit() and 13 <= int(result) <= 24 else 0
    if key == "doz3":
        return 3 if result.isdigit() and 25 <= int(result) <= 36 else 0
    if key == "column1":
        return 3 if result.isdigit() and 1 <= int(result) <= 36 and ((int(result) - 1) % 3) == 0 else 0
    if key == "column2":
        return 3 if result.isdigit() and 1 <= int(result) <= 36 and ((int(result) - 1) % 3) == 1 else 0
    if key == "column3":
        return 3 if result.isdigit() and 1 <= int(result) <= 36 and ((int(result) - 1) % 3) == 2 else 0
    return 0


def _ensure_room(session: Session) -> WheelPlusRoom:
    room = session.scalar(select(WheelPlusRoom).where(WheelPlusRoom.room_key == _room_key()))
    if room is None:
        now = _utcnow()
        room = WheelPlusRoom(
            room_key=_room_key(),
            title="Wheel Plus",
            status="betting",
            round_index=1,
            betting_started_at=now,
            betting_ends_at=now + timedelta(seconds=WHEEL_PLUS_BETTING_SECONDS),
        )
        session.add(room)
        session.flush()
    return room


def _ensure_round(session: Session, room: WheelPlusRoom) -> WheelPlusRound:
    round_row = None
    if room.current_round_id:
        round_row = session.get(WheelPlusRound, room.current_round_id)
    if round_row is not None:
        return round_row

    now = _utcnow()
    round_row = WheelPlusRound(
        room_id=room.id,
        round_index=room.round_index,
        status="betting",
        betting_started_at=now,
        betting_ends_at=now + timedelta(seconds=WHEEL_PLUS_BETTING_SECONDS),
        server_seed_hash=secrets.token_hex(16),
        client_seed="wheel-plus-room",
        nonce=secrets.randbelow(1_000_000),
        result_number="",
        result_color="",
        lucky_numbers_json="[]",
    )
    session.add(round_row)
    session.flush()
    room.current_round_id = round_row.id
    room.status = "betting"
    room.betting_started_at = round_row.betting_started_at
    room.betting_ends_at = round_row.betting_ends_at
    return round_row


def _current_seconds_remaining(round_row: WheelPlusRound) -> int:
    delta = int((round_row.betting_ends_at - _utcnow()).total_seconds())
    return max(0, delta)


def _serialize_round(round_row: WheelPlusRound) -> dict[str, Any]:
    try:
        lucky_numbers = json.loads(round_row.lucky_numbers_json or "[]")
    except Exception:
        lucky_numbers = []
    return {
        "id": round_row.id,
        "round_index": round_row.round_index,
        "status": round_row.status,
        "betting_started_at": round_row.betting_started_at.isoformat(),
        "betting_ends_at": round_row.betting_ends_at.isoformat(),
        "settled_at": round_row.settled_at.isoformat() if round_row.settled_at else None,
        "server_seed_hash": round_row.server_seed_hash,
        "server_seed": round_row.server_seed,
        "client_seed": round_row.client_seed,
        "nonce": round_row.nonce,
        "result_number": round_row.result_number,
        "result_color": round_row.result_color,
        "lucky_numbers": lucky_numbers,
        "total_bet": round_row.total_bet,
        "total_payout": round_row.total_payout,
    }


def _serialize_room(room: WheelPlusRoom, round_row: WheelPlusRound) -> dict[str, Any]:
    return {
        "id": room.id,
        "room_key": room.room_key,
        "title": room.title,
        "status": room.status,
        "round_index": room.round_index,
        "current_round_id": room.current_round_id,
        "seconds_remaining": _current_seconds_remaining(round_row) if round_row.status == "betting" else 0,
    }


def _serialize_live_players(session: Session, round_id: int) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            select(User, func.sum(WheelPlusBet.amount))
            .join(WheelPlusBet, WheelPlusBet.user_id == User.id)
            .where(WheelPlusBet.round_id == round_id)
            .group_by(User.id)
            .order_by(desc(func.sum(WheelPlusBet.amount)))
        )
        .all()
    )
    players = []
    for user, amount in rows:
        bets = session.execute(
            select(WheelPlusBet.cell_key)
            .where(WheelPlusBet.round_id == round_id, WheelPlusBet.user_id == user.id)
        ).scalars().all()
        players.append(
            {
                "id": user.id,
                "telegram_id": user.telegram_id,
                "name": user.first_name or user.username or "noname",
                "username": user.username or "",
                "status": user.status,
                "amount": int(amount or 0),
                "cells": [cell for cell in bets],
            }
        )
    return players


def _serialize_cell_totals(session: Session, round_id: int) -> dict[str, int]:
    rows = (
        session.execute(
            select(WheelPlusBet.cell_key, func.coalesce(func.sum(WheelPlusBet.amount), 0))
            .where(WheelPlusBet.round_id == round_id)
            .group_by(WheelPlusBet.cell_key)
        )
        .all()
    )
    return {str(cell_key): int(total or 0) for cell_key, total in rows}


def _serialize_history(session: Session, limit: int = 12) -> list[dict[str, Any]]:
    rounds = session.execute(
        select(WheelPlusRound).where(WheelPlusRound.status == "settled").order_by(desc(WheelPlusRound.settled_at)).limit(limit)
    ).scalars().all()
    return [_serialize_round(round_row) for round_row in rounds]


def _settle_round(session: Session, room: WheelPlusRoom, round_row: WheelPlusRound) -> dict[str, Any]:
    if round_row.status == "settled":
        return _serialize_round(round_row)

    bets = session.execute(select(WheelPlusBet).where(WheelPlusBet.round_id == round_row.id)).scalars().all()
    result_number = secrets.choice(WHEEL_PLUS_SEQUENCE)
    result_color = _wheel_color(result_number)
    total_bet = sum(int(b.amount or 0) for b in bets)
    total_payout = 0
    per_user: dict[int, dict[str, int]] = defaultdict(lambda: {"bet": 0, "payout": 0, "multiplier": 0})

    for bet in bets:
        multiplier = _cell_multiplier(bet.cell_key, result_number)
        per_user[bet.user_id]["bet"] += int(bet.amount or 0)
        per_user[bet.user_id]["multiplier"] = max(per_user[bet.user_id]["multiplier"], multiplier)
        if multiplier > 0:
            payout = int(bet.amount or 0) * multiplier
            per_user[bet.user_id]["payout"] += payout
            total_payout += payout
            WalletService.payout(
                session,
                bet.user_id,
                payout,
                meta={"game": "wheel_plus", "round_id": round_row.id, "cell_key": bet.cell_key, "result": result_number},
            )

    for user_id, values in per_user.items():
        StatsService.update_after_round(
            session,
            user_id,
            bet=values["bet"],
            payout=values["payout"],
            multiplier=values["multiplier"],
        )

    round_row.status = "settled"
    round_row.settled_at = _utcnow()
    round_row.result_number = result_number
    round_row.result_color = result_color
    round_row.server_seed = secrets.token_hex(32)
    round_row.lucky_numbers_json = json.dumps(_build_lucky_numbers(result_number, round_row.round_index), ensure_ascii=False)
    round_row.total_bet = total_bet
    round_row.total_payout = total_payout

    room.round_index += 1
    room.status = "betting"
    new_round = WheelPlusRound(
        room_id=room.id,
        round_index=room.round_index,
        status="betting",
        betting_started_at=_utcnow(),
        betting_ends_at=_utcnow() + timedelta(seconds=WHEEL_PLUS_BETTING_SECONDS),
        server_seed_hash=secrets.token_hex(16),
        client_seed="wheel-plus-room",
        nonce=secrets.randbelow(1_000_000),
        result_number="",
        result_color="",
        lucky_numbers_json="[]",
    )
    session.add(new_round)
    session.flush()
    room.current_round_id = new_round.id
    room.betting_started_at = new_round.betting_started_at
    room.betting_ends_at = new_round.betting_ends_at
    session.flush()

    return _serialize_round(round_row)


@app.post("/api/wheel-plus/state")
def wheel_plus_state(payload: WheelPlusRoomPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = _ensure_user(db, payload.init_data)
    room = _ensure_room(db)
    current_round = _ensure_round(db, room)

    profile = StatsService.build_profile_payload(db, user)
    profile["text"] = StatsService.format_profile_text(profile)
    snapshot = WalletService.get_snapshot(db, user.id)

    if current_round.status == "settled" and room.current_round_id:
        current_round = _ensure_round(db, room)

    live_players = _serialize_live_players(db, current_round.id)
    cell_totals = _serialize_cell_totals(db, current_round.id)
    history = _serialize_history(db, 12)
    player_total_bet = int(
        db.scalar(
            select(func.coalesce(func.sum(WheelPlusBet.amount), 0)).where(
                WheelPlusBet.round_id == current_round.id,
                WheelPlusBet.user_id == user.id,
            )
        )
        or 0
    )

    room_payload = _serialize_room(room, current_round)
    room_payload["player_total_bet"] = player_total_bet
    room_payload["players_count"] = len(live_players)
    room_payload["total_bet"] = int(sum(int(item["amount"]) for item in live_players))
    room_payload["total_payout"] = int(current_round.total_payout or 0)

    return {
        "status": "success",
        "balance": snapshot.balance,
        "profile": profile,
        "room": room_payload,
        "round": _serialize_round(current_round),
        "history": history,
        "live_players": live_players,
        "cell_totals": cell_totals,
    }


@app.post("/api/wheel-plus/bet")
def wheel_plus_bet(payload: WheelPlusBetPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = _ensure_user(db, payload.init_data)
    room = _ensure_room(db)
    current_round = _ensure_round(db, room)
    amount = int(payload.amount)
    cell_key = _normalize_cell_key(payload.cell_key)

    if current_round.status != "betting" or _current_seconds_remaining(current_round) <= 0:
        raise HTTPException(status_code=409, detail="Ставки уже закрыты")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    if cell_key not in set(CELL_LABELS) and not cell_key.startswith("num"):
        raise HTTPException(status_code=400, detail="Invalid bet cell")

    WalletService.place_bet(
        db,
        user.id,
        amount,
        meta={"game": "wheel_plus", "room_id": room.id, "round_id": current_round.id, "cell_key": cell_key},
    )
    db.add(
        WheelPlusBet(
            room_id=room.id,
            round_id=current_round.id,
            user_id=user.id,
            cell_key=cell_key,
            amount=amount,
        )
    )
    db.flush()

    profile = StatsService.build_profile_payload(db, user)
    profile["text"] = StatsService.format_profile_text(profile)
    snapshot = WalletService.get_snapshot(db, user.id)

    return {
        "status": "success",
        "balance": snapshot.balance,
        "profile": profile,
        "room": {
            **_serialize_room(room, current_round),
            "player_total_bet": int(
                db.scalar(
                    select(func.coalesce(func.sum(WheelPlusBet.amount), 0)).where(
                        WheelPlusBet.round_id == current_round.id,
                        WheelPlusBet.user_id == user.id,
                    )
                )
                or 0
            ),
            "players_count": len(_serialize_live_players(db, current_round.id)),
            "total_bet": int(
                db.scalar(select(func.coalesce(func.sum(WheelPlusBet.amount), 0)).where(WheelPlusBet.round_id == current_round.id))
                or 0
            ),
            "total_payout": int(current_round.total_payout or 0),
        },
        "round": _serialize_round(current_round),
        "history": _serialize_history(db, 12),
        "live_players": _serialize_live_players(db, current_round.id),
        "cell_totals": _serialize_cell_totals(db, current_round.id),
    }


@app.post("/api/wheel-plus/settle")
def wheel_plus_settle(payload: WheelPlusSettlePayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    _ensure_user(db, payload.init_data)
    room = _ensure_room(db)
    current_round = _ensure_round(db, room)

    if current_round.status == "settled":
        return wheel_plus_state(WheelPlusRoomPayload(init_data=payload.init_data), db)

    settled_round = _settle_round(db, room, current_round)
    db.commit()

    room_state = wheel_plus_state(WheelPlusRoomPayload(init_data=payload.init_data), db)
    room_state["settled_round"] = settled_round
    return room_state


@app.post("/api/wheel-plus/ping")
def wheel_plus_ping(payload: WheelPlusRoomPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    return wheel_plus_state(payload, db)
