from __future__ import annotations

import hashlib
import hmac
import json
import random
import secrets
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models import GameRound, User, WheelPlusBet, WheelPlusRoom, WheelPlusRound
from app.services.stats_service import StatsService
from app.services.wallet_service import WalletService

ROOM_KEY = "wheel_plus_room"
ROOM_TITLE = "Wheel Plus"
BETTING_SECONDS = 45
HISTORY_LIMIT = 12

WHEEL_SEQUENCE = [
    "0", "28", "9", "26", "30", "11", "7", "20", "32", "17", "5", "22",
    "34", "15", "3", "24", "36", "13", "1", "00", "27", "10", "25", "29",
    "12", "8", "19", "31", "18", "6", "21", "33", "16", "4", "23", "35",
    "14", "2",
]

RED_NUMBERS = {"1", "3", "5", "7", "9", "12", "14", "16", "18", "19", "21", "23", "25", "27", "30", "32", "34", "36"}
BLACK_NUMBERS = {"2", "4", "6", "8", "10", "11", "13", "15", "17", "20", "22", "24", "26", "28", "29", "31", "33", "35"}

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
    "zero": "0",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash_seed(server_seed: str) -> str:
    return hashlib.sha256(server_seed.encode("utf-8")).hexdigest()


def _normalize_cell_key(cell_key: str) -> str:
    key = str(cell_key or "").strip().lower()
    if key in {"dozen1", "dozen2", "dozen3"}:
        return {"dozen1": "doz1", "dozen2": "doz2", "dozen3": "doz3"}[key]
    if key == "0":
        return "zero"
    return key


def _cell_label(cell_key: str) -> str:
    key = _normalize_cell_key(cell_key)
    if key.startswith("num") and key[3:].isdigit():
        return key[3:]
    return CELL_LABELS.get(key, key)


def _color_of(result: str) -> str:
    value = str(result)
    if value in {"0", "00"}:
        return "green"
    if value in RED_NUMBERS:
        return "red"
    if value in BLACK_NUMBERS:
        return "black"
    return "green"


def _result_from_seed(server_seed: str, client_seed: str, nonce: int) -> str:
    digest = hmac.new(
        server_seed.encode("utf-8"),
        f"{client_seed}:{nonce}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    index = int(digest[:16], 16) % len(WHEEL_SEQUENCE)
    return WHEEL_SEQUENCE[index]


def _lucky_numbers(server_seed: str, client_seed: str, nonce: int) -> list[dict[str, Any]]:
    digest = hmac.new(
        server_seed.encode("utf-8"),
        f"{client_seed}:{nonce}:lucky".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    rng = random.Random(int(digest[:16], 16))
    pool = [value for value in WHEEL_SEQUENCE if value not in {"0", "00"}]
    picked = rng.sample(pool, k=min(3, len(pool)))
    multipliers = [50, 100, 300]
    return [
        {"number": picked[index], "multiplier": multipliers[index]}
        for index in range(min(3, len(picked)))
    ]


def _cell_multiplier(cell_key: str, result: str) -> int:
    key = _normalize_cell_key(cell_key)
    if key.startswith("num") and key[3:].isdigit():
        return 30 if result == key[3:] else 0
    if key == "zero":
        return 30 if result == "0" else 0
    if key in {"red", "black", "even", "odd", "low", "high"}:
        if result in {"0", "00"}:
            return 0
        number = int(result)
        if key == "red" and result in RED_NUMBERS:
            return 2
        if key == "black" and result in BLACK_NUMBERS:
            return 2
        if key == "even" and number % 2 == 0:
            return 2
        if key == "odd" and number % 2 == 1:
            return 2
        if key == "low" and 1 <= number <= 18:
            return 2
        if key == "high" and 19 <= number <= 36:
            return 2
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
    return 0


def _room_or_create(session: Session) -> WheelPlusRoom:
    room = session.scalar(select(WheelPlusRoom).where(WheelPlusRoom.room_key == ROOM_KEY).with_for_update())
    if room is None:
        room = WheelPlusRoom(
            room_key=ROOM_KEY,
            title=ROOM_TITLE,
            status="betting",
            round_index=1,
            betting_started_at=_utcnow(),
            betting_ends_at=_utcnow() + timedelta(seconds=BETTING_SECONDS),
        )
        session.add(room)
        session.flush()
    return room


def _current_round(session: Session, room: WheelPlusRoom) -> WheelPlusRound | None:
    if not room.current_round_id:
        return None
    return session.scalar(select(WheelPlusRound).where(WheelPlusRound.id == room.current_round_id).with_for_update())


def _create_round(session: Session, room: WheelPlusRoom, round_index: int | None = None) -> WheelPlusRound:
    index = int(round_index or room.round_index or 1)
    server_seed = secrets.token_hex(32)
    betting_started_at = _utcnow()
    betting_ends_at = betting_started_at + timedelta(seconds=BETTING_SECONDS)
    round_row = WheelPlusRound(
        room_id=room.id,
        round_index=index,
        status="betting",
        betting_started_at=betting_started_at,
        betting_ends_at=betting_ends_at,
        server_seed_hash=_hash_seed(server_seed),
        server_seed=server_seed,
        client_seed=f"{ROOM_KEY}:{index}",
        nonce=index,
        result_number="",
        result_color="",
        lucky_numbers_json=json.dumps(_lucky_numbers(server_seed, f"{ROOM_KEY}:{index}", index), ensure_ascii=False),
        total_bet=0,
        total_payout=0,
    )
    session.add(round_row)
    session.flush()
    room.current_round_id = round_row.id
    room.status = "betting"
    room.round_index = index
    room.betting_started_at = betting_started_at
    room.betting_ends_at = betting_ends_at
    return round_row


def _ensure_active_round(session: Session, room: WheelPlusRoom) -> WheelPlusRound:
    round_row = _current_round(session, room)
    if round_row is None or round_row.status != "betting":
        round_row = _create_round(session, room, round_index=(room.round_index or 0) + 1 if room.current_round_id else 1)
    return round_row


def _aggregate_round_bets(session: Session, round_id: int) -> tuple[list[dict[str, Any]], dict[str, int], int]:
    rows = session.execute(
        select(WheelPlusBet, User)
        .join(User, User.id == WheelPlusBet.user_id)
        .where(WheelPlusBet.round_id == round_id)
        .order_by(WheelPlusBet.created_at.asc())
    ).all()

    players: dict[int, dict[str, Any]] = {}
    cell_totals: dict[str, int] = defaultdict(int)
    total_bet = 0

    for bet, user in rows:
        key = _normalize_cell_key(bet.cell_key)
        cell_totals[key] += bet.amount
        total_bet += bet.amount

        player = players.setdefault(
            user.id,
            {
                "user_id": user.id,
                "telegram_id": user.telegram_id,
                "name": user.username or user.first_name or "noname",
                "status": user.status,
                "role": user.role,
                "amount": 0,
                "cells": [],
            },
        )
        player["amount"] += bet.amount
        player["cells"].append(key)

    live_players = sorted(players.values(), key=lambda item: item["amount"], reverse=True)
    for key in list(cell_totals.keys()):
        cell_totals[key] = int(cell_totals[key])
    return live_players, dict(cell_totals), total_bet


def _round_dict(round_row: WheelPlusRound, *, include_secret: bool = False, players_count: int = 0) -> dict[str, Any]:
    return {
        "id": round_row.id,
        "room_id": round_row.room_id,
        "round_index": round_row.round_index,
        "status": round_row.status,
        "result_number": round_row.result_number or "",
        "result_color": round_row.result_color or "black",
        "server_seed_hash": round_row.server_seed_hash,
        "server_seed": round_row.server_seed if include_secret else "",
        "client_seed": round_row.client_seed,
        "nonce": round_row.nonce,
        "lucky_numbers": json.loads(round_row.lucky_numbers_json or "[]"),
        "total_bet": round_row.total_bet,
        "total_payout": round_row.total_payout,
        "betting_started_at": round_row.betting_started_at.isoformat(),
        "betting_ends_at": round_row.betting_ends_at.isoformat(),
        "settled_at": round_row.settled_at.isoformat() if round_row.settled_at else "",
        "players_count": players_count,
    }


def _recent_history(session: Session, room_id: int) -> list[dict[str, Any]]:
    rounds = session.execute(
        select(WheelPlusRound)
        .where(WheelPlusRound.room_id == room_id)
        .where(WheelPlusRound.status == "settled")
        .order_by(desc(WheelPlusRound.settled_at), desc(WheelPlusRound.id))
        .limit(HISTORY_LIMIT)
    ).scalars().all()
    history: list[dict[str, Any]] = []
    for round_row in rounds:
        history.append(_round_dict(round_row, include_secret=True))
    return history


def _settle_round(session: Session, room: WheelPlusRoom, round_row: WheelPlusRound) -> dict[str, Any] | None:
    if round_row.status != "betting":
        return None
    if round_row.betting_ends_at > _utcnow():
        return None

    bets = session.execute(
        select(WheelPlusBet, User)
        .join(User, User.id == WheelPlusBet.user_id)
        .where(WheelPlusBet.round_id == round_row.id)
        .order_by(WheelPlusBet.created_at.asc())
    ).all()

    result_number = _result_from_seed(round_row.server_seed, round_row.client_seed, round_row.nonce)
    result_color = _color_of(result_number)
    lucky_numbers = _lucky_numbers(round_row.server_seed, round_row.client_seed, round_row.nonce)

    user_bets: dict[int, int] = defaultdict(int)
    user_payouts: dict[int, int] = defaultdict(int)
    user_max_multipliers: dict[int, int] = defaultdict(int)

    total_bet = 0
    total_payout = 0
    cell_totals: dict[str, int] = defaultdict(int)

    for bet, user in bets:
        key = _normalize_cell_key(bet.cell_key)
        cell_totals[key] += bet.amount
        total_bet += bet.amount
        user_bets[user.id] += bet.amount

        multiplier = _cell_multiplier(key, result_number)
        if multiplier > 0:
            payout = bet.amount * multiplier
            total_payout += payout
            user_payouts[user.id] += payout
            user_max_multipliers[user.id] = max(user_max_multipliers[user.id], multiplier)

    for user_id, payout in user_payouts.items():
        WalletService.payout(session, user_id, payout, meta={"game": "wheel_plus_room", "room_id": room.id, "round_id": round_row.id})

    for user_id, bet_amount in user_bets.items():
        StatsService.update_after_round(
            session,
            user_id,
            bet=bet_amount,
            payout=user_payouts.get(user_id, 0),
            multiplier=user_max_multipliers.get(user_id, 0),
        )

    round_row.status = "settled"
    round_row.result_number = result_number
    round_row.result_color = result_color
    round_row.lucky_numbers_json = json.dumps(lucky_numbers, ensure_ascii=False)
    round_row.total_bet = total_bet
    round_row.total_payout = total_payout
    round_row.settled_at = _utcnow()

    for user_id, bet_amount in user_bets.items():
        round_result = {
            "result_number": result_number,
            "result_color": result_color,
            "lucky_numbers": lucky_numbers,
            "room_id": room.id,
            "round_id": round_row.id,
        }
        session.add(
            GameRound(
                user_id=user_id,
                game_type="wheel_plus_room",
                bet=bet_amount,
                payout=user_payouts.get(user_id, 0),
                multiplier=user_max_multipliers.get(user_id, 0),
                client_seed=round_row.client_seed,
                server_seed_hash=round_row.server_seed_hash,
                server_seed=round_row.server_seed,
                nonce=round_row.nonce,
                result_json=json.dumps(round_result, ensure_ascii=False),
            )
        )

    room.status = "settled"
    room.updated_at = _utcnow()
    session.flush()

    settled = _round_dict(round_row, include_secret=True)
    settled["lucky_numbers"] = lucky_numbers
    settled["result_number"] = result_number
    settled["result_color"] = result_color
    settled["total_bet"] = total_bet
    settled["total_payout"] = total_payout
    settled["players_count"] = len(user_bets)
    return settled


def _serialize_profile(session: Session, user: User) -> dict[str, Any]:
    profile = StatsService.build_profile_payload(session, user)
    profile["text"] = StatsService.format_profile_text(profile)
    return profile


def build_state(session: Session, user: User, *, settle_if_due: bool = True) -> dict[str, Any]:
    room = _room_or_create(session)
    current_round = _ensure_active_round(session, room)
    settled_round = None

    if settle_if_due and current_round.status == "betting" and current_round.betting_ends_at <= _utcnow():
        settled_round = _settle_round(session, room, current_round)
        room.round_index = (current_round.round_index or 1) + 1
        current_round = _create_round(session, room, round_index=room.round_index)

    live_players, cell_totals, total_bet = _aggregate_round_bets(session, current_round.id)
    history = _recent_history(session, room.id)
    profile = _serialize_profile(session, user)

    room_payload = {
        "room_key": room.room_key,
        "title": room.title,
        "status": current_round.status,
        "round_index": current_round.round_index,
        "current_round_id": current_round.id,
        "seconds_remaining": max(0, int((current_round.betting_ends_at - _utcnow()).total_seconds())),
        "total_bet": total_bet,
        "players_count": len(live_players),
        "betting_started_at": current_round.betting_started_at.isoformat(),
        "betting_ends_at": current_round.betting_ends_at.isoformat(),
    }

    current_round_payload = _round_dict(current_round, include_secret=False, players_count=len(live_players))
    current_round_payload["total_bet"] = total_bet
    current_round_payload["lucky_numbers"] = json.loads(current_round.lucky_numbers_json or "[]")

    payload: dict[str, Any] = {
        "profile": profile,
        "balance": profile.get("balance", 0),
        "room": room_payload,
        "round": current_round_payload,
        "history": history,
        "live_players": live_players,
        "cell_totals": cell_totals,
    }
    if settled_round:
        payload["settled_round"] = settled_round
    return payload


def place_bet(session: Session, user: User, cell_key: str, amount: int) -> dict[str, Any]:
    room = _room_or_create(session)
    current_round = _ensure_active_round(session, room)
    if current_round.status != "betting" or current_round.betting_ends_at <= _utcnow():
        raise ValueError("Ставки уже закрыты")
    if amount <= 0:
        raise ValueError("amount must be positive")

    normalized = _normalize_cell_key(cell_key)
    if normalized not in CELL_LABELS and not normalized.startswith("num"):
        if normalized != "zero":
            raise ValueError("Invalid cell key")

    WalletService.place_bet(
        session,
        user.id,
        amount,
        meta={"game": "wheel_plus_room", "room_id": room.id, "round_id": current_round.id, "cell_key": normalized},
    )
    session.add(
        WheelPlusBet(
            room_id=room.id,
            round_id=current_round.id,
            user_id=user.id,
            cell_key=normalized,
            amount=amount,
        )
    )
    session.flush()
    return build_state(session, user, settle_if_due=False)


def settle_due_round(session: Session, user: User) -> dict[str, Any]:
    room = _room_or_create(session)
    current_round = _ensure_active_round(session, room)
    settled_round = _settle_round(session, room, current_round)
    if settled_round:
        room.round_index = (current_round.round_index or 1) + 1
        current_round = _create_round(session, room, round_index=room.round_index)
    payload = build_state(session, user, settle_if_due=False)
    if settled_round:
        payload["settled_round"] = settled_round
    return payload
