from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.schemas import WheelPlusBetPayload, WheelPlusFairRevealPayload, WheelPlusRoomPayload
from app.db.models import AdminAuditLog, GameRound, User, Wallet, WheelPlusBet, WheelPlusRoom, WheelPlusRound
from app.services.stats_service import StatsService
from app.services.wallet_service import WalletService

WHEEL_PLUS_ROOM_KEY = "wheel_plus_room"
WHEEL_PLUS_BETTING_SECONDS = 25
WHEEL_PLUS_REVEAL_SECONDS = 12
WHEEL_PLUS_TOP_HISTORY = 12

WHEEL_PLUS_SEQUENCE = [
    "2", "8", "12", "15", "18", "24", "30", "36", "5", "7", "11", "14",
    "17", "20", "23", "26", "29", "32", "1", "3", "4", "6", "9", "10",
    "13", "16", "19", "21", "22", "25", "27", "28", "31", "33", "34", "35", "0",
]

LUCKY_MULTIPLIERS = {"2": 50, "8": 100, "12": 300}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_seed(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _ensure_room(session: Session) -> WheelPlusRoom:
    room = session.scalar(select(WheelPlusRoom).where(WheelPlusRoom.room_key == WHEEL_PLUS_ROOM_KEY))
    if room is None:
        room = WheelPlusRoom(room_key=WHEEL_PLUS_ROOM_KEY, title="Wheel Plus", status="betting", round_index=1)
        session.add(room)
        session.flush()
    return room


def _serialize_round(session: Session, round_row: WheelPlusRound) -> dict[str, Any]:
    bets = session.execute(
        select(WheelPlusBet, User)
        .join(User, User.id == WheelPlusBet.user_id)
        .where(WheelPlusBet.round_id == round_row.id)
        .order_by(desc(WheelPlusBet.amount), desc(WheelPlusBet.created_at))
    ).all()

    betting_users: list[dict[str, Any]] = []
    seen_user_ids: set[int] = set()
    for bet, user in bets:
        if user.id in seen_user_ids:
            continue
        seen_user_ids.add(user.id)
        wallet = session.scalar(select(Wallet).where(Wallet.user_id == user.id))
        betting_users.append(
            {
                "telegram_id": user.telegram_id,
                "username": user.username or user.first_name or "noname",
                "status": user.status,
                "balance": wallet.balance if wallet else 0,
                "total_bet": int(sum(item.amount for item, linked_user in bets if linked_user.id == user.id)),
            }
        )

    bets_payload = [
        {
            "id": bet.id,
            "telegram_id": user.telegram_id,
            "username": user.username or user.first_name or "noname",
            "cell_key": bet.cell_key,
            "amount": bet.amount,
            "created_at": bet.created_at.isoformat(),
        }
        for bet, user in bets
    ]

    return {
        "id": round_row.id,
        "round_index": round_row.round_index,
        "status": round_row.status,
        "betting_started_at": round_row.betting_started_at.isoformat(),
        "betting_ends_at": round_row.betting_ends_at.isoformat(),
        "settled_at": round_row.settled_at.isoformat() if round_row.settled_at else None,
        "server_seed_hash": round_row.server_seed_hash,
        "server_seed": round_row.server_seed if round_row.status == "settled" else "",
        "client_seed": round_row.client_seed,
        "nonce": round_row.nonce,
        "result_number": round_row.result_number,
        "result_color": round_row.result_color,
        "lucky_numbers": json.loads(round_row.lucky_numbers_json or "[]"),
        "total_bet": round_row.total_bet,
        "total_payout": round_row.total_payout,
        "bets": bets_payload,
        "live_players": betting_users,
    }


def _settle_round(session: Session, room: WheelPlusRoom, round_row: WheelPlusRound) -> WheelPlusRound:
    if round_row.status == "settled":
        return round_row

    server_seed = secrets.token_hex(16)
    client_seed = round_row.client_seed or "wheel-plus-room"
    nonce = round_row.nonce or secrets.randbelow(1_000_000)
    seed_material = f"{server_seed}:{client_seed}:{nonce}:{round_row.round_index}"
    digest = hashlib.sha256(seed_material.encode("utf-8")).hexdigest()
    sequence_index = int(digest[:8], 16) % len(WHEEL_PLUS_SEQUENCE)
    result_number = WHEEL_PLUS_SEQUENCE[sequence_index]
    result_color = "green" if result_number in {"0"} else ("red" if result_number in {"2", "8", "12", "18", "24", "30", "36", "5", "7", "11", "14", "15", "20", "23", "26", "29", "32"} else "black")

    lucky_numbers = [
        {
            "number": num,
            "multiplier": LUCKY_MULTIPLIERS[num],
        }
        for num in WHEEL_PLUS_SEQUENCE[:3]
    ]

    bets = session.execute(select(WheelPlusBet).where(WheelPlusBet.round_id == round_row.id)).scalars().all()
    total_payout = 0

    result_multiplier = LUCKY_MULTIPLIERS.get(result_number, 0)
    for bet in bets:
        payout = bet.amount * result_multiplier if bet.cell_key == result_number and result_multiplier > 0 else 0
        if payout > 0:
            WalletService.payout(session, bet.user_id, payout, meta={"game": "wheel_plus", "round_id": round_row.id, "result": result_number})
            StatsService.update_after_round(session, bet.user_id, bet=bet.amount, payout=payout, multiplier=result_multiplier)
            total_payout += payout
        else:
            StatsService.update_after_round(session, bet.user_id, bet=bet.amount, payout=0, multiplier=0)

    round_row.status = "settled"
    round_row.settled_at = _now()
    round_row.server_seed = server_seed
    round_row.nonce = nonce
    round_row.client_seed = client_seed
    round_row.result_number = result_number
    round_row.result_color = result_color
    round_row.total_bet = sum(bet.amount for bet in bets)
    round_row.total_payout = total_payout
    round_row.lucky_numbers_json = json.dumps(lucky_numbers, ensure_ascii=False)

    room.status = "betting"
    room.round_index = round_row.round_index + 1
    room.current_round_id = None
    room.betting_started_at = _now()
    room.betting_ends_at = _now() + timedelta(seconds=WHEEL_PLUS_BETTING_SECONDS)

    session.add(round_row)
    session.add(room)
    session.flush()
    return round_row


def _start_new_round(session: Session, room: WheelPlusRoom) -> WheelPlusRound:
    round_row = WheelPlusRound(
        room_id=room.id,
        round_index=room.round_index,
        status="betting",
        betting_started_at=_now(),
        betting_ends_at=_now() + timedelta(seconds=WHEEL_PLUS_BETTING_SECONDS),
        server_seed_hash=_hash_seed(secrets.token_hex(16)),
        server_seed="",
        client_seed="wheel-plus-room",
        nonce=0,
        result_number="",
        result_color="",
        lucky_numbers_json=json.dumps([], ensure_ascii=False),
        total_bet=0,
        total_payout=0,
    )
    session.add(round_row)
    session.flush()
    room.status = "betting"
    room.current_round_id = round_row.id
    room.betting_started_at = round_row.betting_started_at
    room.betting_ends_at = round_row.betting_ends_at
    session.add(room)
    session.flush()
    return round_row


def _get_current_round(session: Session, room: WheelPlusRoom) -> WheelPlusRound:
    round_row = None
    if room.current_round_id:
        round_row = session.scalar(select(WheelPlusRound).where(WheelPlusRound.id == room.current_round_id))

    if round_row is None:
        round_row = session.scalar(
            select(WheelPlusRound)
            .where(WheelPlusRound.room_id == room.id)
            .order_by(desc(WheelPlusRound.round_index))
        )
        if round_row is not None and round_row.status != "settled":
            room.current_round_id = round_row.id

    if round_row is None:
        return _start_new_round(session, room)

    if round_row.status != "settled" and round_row.betting_ends_at <= _now():
        round_row = _settle_round(session, room, round_row)
        round_row = _start_new_round(session, room)

    session.add(room)
    session.flush()
    return round_row


def get_room_snapshot(session: Session) -> dict[str, Any]:
    room = _ensure_room(session)
    current_round = _get_current_round(session, room)
    recent_rounds = session.execute(
        select(WheelPlusRound)
        .where(WheelPlusRound.room_id == room.id)
        .order_by(desc(WheelPlusRound.round_index))
        .limit(WHEEL_PLUS_TOP_HISTORY)
    ).scalars().all()

    players = session.execute(
        select(User, Wallet)
        .join(Wallet, Wallet.user_id == User.id)
        .where(User.status == "active")
        .order_by(desc(Wallet.balance))
        .limit(12)
    ).all()

    return {
        "room": {
            "id": room.id,
            "title": room.title,
            "status": room.status,
            "round_index": room.round_index,
            "betting_started_at": room.betting_started_at.isoformat() if room.betting_started_at else None,
            "betting_ends_at": room.betting_ends_at.isoformat() if room.betting_ends_at else None,
        },
        "current_round": _serialize_round(session, current_round),
        "recent_rounds": [_serialize_round(session, round_row) for round_row in recent_rounds],
        "players": [
            {
                "telegram_id": user.telegram_id,
                "username": user.username or user.first_name or "noname",
                "balance": wallet.balance,
                "stars_balance": wallet.stars_balance,
            }
            for user, wallet in players
        ],
    }


def place_bet(session: Session, user: User, cell_key: str, amount: int) -> dict[str, Any]:
    room = _ensure_room(session)
    round_row = _get_current_round(session, room)
    if round_row.status != "betting":
        raise HTTPException(status_code=409, detail="Betting is closed")
    if round_row.betting_ends_at <= _now():
        round_row = _settle_round(session, room, round_row)
        round_row = _start_new_round(session, room)

    snapshot = WalletService.place_bet(session, user.id, amount, meta={"game": "wheel_plus", "cell_key": cell_key, "round_id": round_row.id})
    existing_bet = session.scalar(
        select(WheelPlusBet).where(
            WheelPlusBet.round_id == round_row.id,
            WheelPlusBet.user_id == user.id,
            WheelPlusBet.cell_key == cell_key,
        )
    )
    if existing_bet is None:
        existing_bet = WheelPlusBet(
            room_id=room.id,
            round_id=round_row.id,
            user_id=user.id,
            cell_key=cell_key,
            amount=0,
        )
        session.add(existing_bet)
    existing_bet.amount += amount
    round_row.total_bet += amount
    session.add(round_row)
    session.flush()

    return {"balance": snapshot.balance, "round": _serialize_round(session, round_row)}


def reveal_round(session: Session, round_id: int) -> dict[str, Any]:
    round_row = session.scalar(select(WheelPlusRound).where(WheelPlusRound.id == round_id))
    if round_row is None:
        raise HTTPException(status_code=404, detail="Round not found")
    if round_row.status != "settled" and round_row.betting_ends_at > _now():
        raise HTTPException(status_code=409, detail="Round is not settled yet")
    if round_row.status != "settled":
        room = session.scalar(select(WheelPlusRoom).where(WheelPlusRoom.id == round_row.room_id))
        if room is None:
            raise HTTPException(status_code=404, detail="Room not found")
        round_row = _settle_round(session, room, round_row)
        session.commit()
    return {
        "round": _serialize_round(session, round_row),
        "fair": {
            "server_seed_hash": round_row.server_seed_hash,
            "server_seed": round_row.server_seed,
            "client_seed": round_row.client_seed,
            "nonce": round_row.nonce,
            "result_number": round_row.result_number,
            "result_color": round_row.result_color,
        },
    }


def admin_force_settle(session: Session) -> dict[str, Any]:
    room = _ensure_room(session)
    current_round = _get_current_round(session, room)
    if current_round.status == "settled":
        return {"status": "already_settled"}
    settled = _settle_round(session, room, current_round)
    session.commit()
    return {"status": "success", "round": _serialize_round(session, settled)}
