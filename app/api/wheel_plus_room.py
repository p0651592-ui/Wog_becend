from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import User, Wallet
from app.db.room_models import WheelPlusBet, WheelPlusRound
from app.db.session import get_db
from app.services.stats_service import StatsService
from app.services.telegram_auth import verify_telegram_init_data
from app.services.wallet_service import WalletService

router = APIRouter(prefix="/api/wheel-plus", tags=["wheel-plus"])

WHEEL_PLUS_SEQUENCE = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10,
    5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26,
]

NUMBER_COLORS = {
    0: "green",
    1: "red",
    2: "black",
    3: "red",
    4: "black",
    5: "red",
    6: "black",
    7: "red",
    8: "black",
    9: "red",
    10: "black",
    11: "black",
    12: "red",
    13: "black",
    14: "red",
    15: "black",
    16: "red",
    17: "black",
    18: "red",
    19: "red",
    20: "black",
    21: "red",
    22: "black",
    23: "red",
    24: "black",
    25: "red",
    26: "black",
    27: "red",
    28: "black",
    29: "black",
    30: "red",
    31: "black",
    32: "red",
    33: "black",
    34: "red",
    35: "black",
    36: "red",
}

LUCKY_MULTIPLIERS = [50, 100, 150, 200, 250, 300, 350, 400, 450, 500]
OPEN_ROUND_SECONDS = 20
DEFAULT_CLIENT_SEED = "wheel-plus-room"
VALID_BET_CELLS = {
    "red", "black", "even", "odd", "low", "high",
    "doz1", "doz2", "doz3",
    *{f"num{i}" for i in range(37)},
}


class InitDataPayload(BaseModel):
    init_data: str = Field(default="")


class WheelPlusBetPayload(InitDataPayload):
    bet_cell: str = Field(default="")
    amount: int = Field(gt=0)


class WheelPlusRoundRefPayload(InitDataPayload):
    round_id: int = Field(gt=0)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _is_admin_ready() -> bool:
    return bool(settings.telegram_bot_token)


def _get_user(session: Session, init_data: str) -> tuple[User, dict[str, Any]]:
    if not _is_admin_ready():
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN is not configured")

    telegram_user = verify_telegram_init_data(init_data, settings.telegram_bot_token)
    if not telegram_user:
        raise HTTPException(status_code=403, detail="Telegram authentication failed")

    telegram_id = int(telegram_user["id"])
    username = str(telegram_user.get("username") or "")
    first_name = str(telegram_user.get("first_name") or telegram_user.get("last_name") or "noname")
    user = WalletService.get_or_create_user(session, telegram_id, username=username, first_name=first_name)
    session.flush()
    return user, telegram_user


def _seed_hash(server_seed: str) -> str:
    return hashlib.sha256(server_seed.encode("utf-8")).hexdigest()


def _digest_int(server_seed: str, client_seed: str, nonce: int, label: str, modulo: int) -> int:
    if modulo <= 0:
        return 0
    payload = f"{client_seed}|{nonce}|{label}".encode("utf-8")
    digest = hmac.new(server_seed.encode("utf-8"), payload, hashlib.sha256).digest()
    return int.from_bytes(digest[:8], "big") % modulo


def _color_of_number(number: int) -> str:
    return NUMBER_COLORS.get(int(number), "green")


def _pick_winning_number(server_seed: str, client_seed: str, nonce: int) -> int:
    return WHEEL_PLUS_SEQUENCE[_digest_int(server_seed, client_seed, nonce, "winning-number", len(WHEEL_PLUS_SEQUENCE))]


def _pick_lucky_numbers(server_seed: str, client_seed: str, nonce: int, winning_number: int) -> list[dict[str, int]]:
    pool = [num for num in range(37)]
    lucky_numbers: list[dict[str, int]] = []

    for slot in range(3):
        if not pool:
            break
        index = _digest_int(server_seed, client_seed, nonce, f"lucky-index-{slot}", len(pool))
        number = pool.pop(index)
        multiplier = LUCKY_MULTIPLIERS[
            _digest_int(server_seed, client_seed, nonce, f"lucky-mult-{slot}", len(LUCKY_MULTIPLIERS))
        ]
        lucky_numbers.append({"num": number, "mult": multiplier})

    # Keep the winning number available in the room metadata even if it was not selected as lucky.
    lucky_numbers.sort(key=lambda item: item["num"])
    return lucky_numbers


def _lucky_multiplier_for_number(lucky_numbers: list[dict[str, int]], number: int) -> int:
    for item in lucky_numbers:
        if int(item["num"]) == int(number):
            return int(item["mult"])
    return 0


def _cell_payout_multiplier(cell: str, winning_number: int) -> int:
    color = _color_of_number(winning_number)
    if cell == "red":
        return 2 if color == "red" else 0
    if cell == "black":
        return 2 if color == "black" else 0
    if cell == "even":
        return 2 if winning_number != 0 and winning_number % 2 == 0 else 0
    if cell == "odd":
        return 2 if winning_number % 2 == 1 else 0
    if cell == "low":
        return 2 if 1 <= winning_number <= 18 else 0
    if cell == "high":
        return 2 if 19 <= winning_number <= 36 else 0
    if cell == "doz1":
        return 3 if 1 <= winning_number <= 12 else 0
    if cell == "doz2":
        return 3 if 13 <= winning_number <= 24 else 0
    if cell == "doz3":
        return 3 if 25 <= winning_number <= 36 else 0
    if cell.startswith("num"):
        try:
            number = int(cell.replace("num", ""))
        except ValueError:
            return 0
        if number == winning_number:
            return 30
    return 0


def _ensure_current_round(session: Session) -> tuple[WheelPlusRound, WheelPlusRound | None]:
    """Return the active round, resolving the previous one if it has expired."""
    latest_round = session.scalar(select(WheelPlusRound).order_by(desc(WheelPlusRound.round_index)).with_for_update())
    if latest_round is None:
        created = _create_round(session)
        return created, None

    if latest_round.status == "open" and latest_round.ends_at <= _utcnow():
        resolved = _resolve_round(session, latest_round)
        created = _create_round(session)
        return created, resolved

    if latest_round.status != "open":
        created = _create_round(session)
        return created, None

    return latest_round, None


def _create_round(session: Session) -> WheelPlusRound:
    next_index = int(session.scalar(select(func.coalesce(func.max(WheelPlusRound.round_index), 0))) or 0) + 1
    server_seed = secrets.token_hex(32)
    round_row = WheelPlusRound(
        round_index=next_index,
        status="open",
        client_seed=DEFAULT_CLIENT_SEED,
        server_seed_hash=_seed_hash(server_seed),
        server_seed=server_seed,
        nonce=next_index,
        started_at=_utcnow(),
        ends_at=_utcnow() + timedelta(seconds=OPEN_ROUND_SECONDS),
    )
    session.add(round_row)
    session.flush()
    return round_row


def _resolve_round(session: Session, round_row: WheelPlusRound) -> WheelPlusRound:
    if round_row.status == "resolved":
        return round_row

    winning_number = _pick_winning_number(round_row.server_seed, round_row.client_seed, round_row.nonce)
    lucky_numbers = _pick_lucky_numbers(round_row.server_seed, round_row.client_seed, round_row.nonce, winning_number)
    lucky_map = {int(item["num"]): int(item["mult"]) for item in lucky_numbers}
    winning_color = _color_of_number(winning_number)

    bet_rows = session.execute(select(WheelPlusBet).where(WheelPlusBet.round_id == round_row.id)).scalars().all()
    if not bet_rows:
        round_row.status = "resolved"
        round_row.resolved_at = _utcnow()
        round_row.winning_number = str(winning_number)
        round_row.winning_color = winning_color
        round_row.lucky_numbers_json = json.dumps(lucky_numbers, ensure_ascii=False)
        round_row.total_bets = 0
        round_row.total_players = 0
        round_row.total_payout = 0
        round_row.result_json = json.dumps(
            {
                "winning_number": winning_number,
                "winning_color": winning_color,
                "lucky_numbers": lucky_numbers,
                "total_bets": 0,
                "total_players": 0,
                "total_payout": 0,
            },
            ensure_ascii=False,
        )
        session.flush()
        return round_row

    by_user: dict[int, dict[str, Any]] = defaultdict(lambda: {"bet": 0, "payout": 0, "multiplier": 0})
    total_payout = 0

    for bet in bet_rows:
        multiplier = _cell_payout_multiplier(bet.bet_cell, winning_number)
        lucky_multiplier = 0
        if bet.bet_cell.startswith("num"):
            try:
                bet_number = int(bet.bet_cell.replace("num", ""))
            except ValueError:
                bet_number = -1
            lucky_multiplier = _lucky_multiplier_for_number(lucky_numbers, bet_number)
            if lucky_multiplier > 0 and bet_number == winning_number:
                multiplier = max(multiplier, lucky_multiplier)

        payout = bet.amount * multiplier if multiplier > 0 else 0
        bet.payout = payout
        bet.is_winner = payout > 0
        total_payout += payout

        summary = by_user[bet.user_id]
        summary["bet"] += bet.amount
        summary["payout"] += payout
        summary["multiplier"] = max(summary["multiplier"], multiplier)

        if payout > 0:
            WalletService.payout(
                session,
                bet.user_id,
                payout,
                meta={"game": "wheel_plus", "round_id": round_row.id, "bet_cell": bet.bet_cell},
            )

    for user_id, summary in by_user.items():
        StatsService.update_after_round(
            session,
            user_id,
            bet=summary["bet"],
            payout=summary["payout"],
            multiplier=summary["multiplier"],
        )

    round_row.status = "resolved"
    round_row.resolved_at = _utcnow()
    round_row.winning_number = str(winning_number)
    round_row.winning_color = winning_color
    round_row.lucky_numbers_json = json.dumps(lucky_numbers, ensure_ascii=False)
    round_row.total_bets = sum(bet.amount for bet in bet_rows)
    round_row.total_players = len(by_user)
    round_row.total_payout = total_payout
    round_row.result_json = json.dumps(
        {
            "winning_number": winning_number,
            "winning_color": winning_color,
            "lucky_numbers": lucky_numbers,
            "total_bets": round_row.total_bets,
            "total_players": round_row.total_players,
            "total_payout": total_payout,
        },
        ensure_ascii=False,
    )
    session.flush()
    return round_row


def _format_round_payload(session: Session, round_row: WheelPlusRound, user_id: int | None = None) -> dict[str, Any]:
    lucky_numbers = json.loads(round_row.lucky_numbers_json or "[]")
    result_json = json.loads(round_row.result_json or "{}")
    my_result: dict[str, Any] = {"amount_bet": 0, "amount_won": 0, "is_lucky_hit": False, "lucky_bonus": 0}

    if user_id is not None:
        user_bets = session.execute(
            select(WheelPlusBet).where(
                WheelPlusBet.round_id == round_row.id,
                WheelPlusBet.user_id == user_id,
            )
        ).scalars().all()
        if user_bets:
            amount_bet = sum(bet.amount for bet in user_bets)
            amount_won = sum(bet.payout for bet in user_bets)
            lucky_bonus = 0
            is_lucky_hit = False
            for bet in user_bets:
                if bet.bet_cell.startswith("num"):
                    try:
                        number = int(bet.bet_cell.replace("num", ""))
                    except ValueError:
                        number = -1
                    if number == int(round_row.winning_number or 0):
                        lucky_bonus = max(lucky_bonus, _lucky_multiplier_for_number(lucky_numbers, number))
                        is_lucky_hit = lucky_bonus > 0
            my_result = {
                "amount_bet": amount_bet,
                "amount_won": amount_won,
                "is_lucky_hit": is_lucky_hit,
                "lucky_bonus": lucky_bonus,
            }

    return {
        "id": round_row.id,
        "round_index": round_row.round_index,
        "status": round_row.status,
        "winning_number": round_row.winning_number,
        "winning_color": round_row.winning_color,
        "server_seed_hash": round_row.server_seed_hash,
        "server_seed": round_row.server_seed if round_row.status == "resolved" else "",
        "client_seed": round_row.client_seed,
        "nonce": round_row.nonce,
        "started_at": round_row.started_at.isoformat(),
        "ends_at": round_row.ends_at.isoformat(),
        "seconds_remaining": max(0, int((round_row.ends_at - _utcnow()).total_seconds())) if round_row.status == "open" else 0,
        "lucky_numbers": lucky_numbers,
        "result": result_json,
        "total_bets": round_row.total_bets,
        "total_players": round_row.total_players,
        "total_payout": round_row.total_payout,
        "my_result": my_result,
    }


def _room_snapshot(session: Session, user_id: int | None = None) -> dict[str, Any]:
    current_round, resolved_round = _ensure_current_round(session)

    history_rounds = session.execute(
        select(WheelPlusRound)
        .where(WheelPlusRound.status == "resolved")
        .order_by(desc(WheelPlusRound.round_index))
        .limit(10)
    ).scalars().all()

    live_rows = session.execute(
        select(WheelPlusBet, User)
        .join(User, User.id == WheelPlusBet.user_id)
        .where(WheelPlusBet.round_id == current_round.id)
        .order_by(desc(WheelPlusBet.amount), desc(WheelPlusBet.created_at))
    ).all()

    live_map: dict[int, dict[str, Any]] = {}
    for bet, user in live_rows:
        entry = live_map.setdefault(
            user.id,
            {
                "telegram_id": user.telegram_id,
                "name": user.username or user.first_name or "noname",
                "amount": 0,
                "cell": bet.bet_cell,
                "bets_count": 0,
            },
        )
        entry["amount"] += bet.amount
        entry["bets_count"] += 1
        entry["cell"] = bet.bet_cell

    live_players = sorted(live_map.values(), key=lambda item: item["amount"], reverse=True)
    profile_balance = None
    profile_stars = None
    profile_name = None
    if user_id is not None:
        wallet = session.scalar(select(Wallet).where(Wallet.user_id == user_id))
        if wallet is not None:
            profile_balance = wallet.balance
            profile_stars = wallet.stars_balance
        user = session.scalar(select(User).where(User.id == user_id))
        if user is not None:
            profile_name = user.username or user.first_name or "noname"

    return {
        "room": {
            "name": "Wheel Plus",
            "phase": current_round.status,
            "round_index": current_round.round_index,
            "seconds_remaining": max(0, int((current_round.ends_at - _utcnow()).total_seconds())),
            "next_round_in": max(0, int((current_round.ends_at - _utcnow()).total_seconds())),
        },
        "current_round": _format_round_payload(session, current_round, user_id=user_id),
        "resolved_round": _format_round_payload(session, resolved_round, user_id=user_id) if resolved_round else None,
        "history": [_format_round_payload(session, row, user_id=user_id) for row in history_rounds],
        "live_players": live_players[:12],
        "profile": {
            "name": profile_name,
            "balance": profile_balance,
            "stars": profile_stars,
        },
    }


@router.post("/state")
def get_state(payload: InitDataPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = _get_user(db, payload.init_data)
    snapshot = _room_snapshot(db, user_id=user.id)
    db.commit()
    return snapshot


@router.post("/bet")
def place_bet(payload: WheelPlusBetPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    if payload.bet_cell not in VALID_BET_CELLS:
        raise HTTPException(status_code=400, detail="Invalid bet cell")

    user, _ = _get_user(db, payload.init_data)
    current_round, resolved_round = _ensure_current_round(db)
    if resolved_round is not None and current_round.status == "open":
        # A fresh round was created after resolving the expired one.
        pass

    if current_round.status != "open":
        raise HTTPException(status_code=409, detail="Round is not open")

    WalletService.place_bet(
        db,
        user.id,
        payload.amount,
        meta={"game": "wheel_plus", "round_id": current_round.id, "bet_cell": payload.bet_cell},
    )

    existing_bet = db.scalar(
        select(WheelPlusBet).where(
            WheelPlusBet.round_id == current_round.id,
            WheelPlusBet.user_id == user.id,
            WheelPlusBet.bet_cell == payload.bet_cell,
        )
    )
    if existing_bet is None:
        db.add(
            WheelPlusBet(
                round_id=current_round.id,
                user_id=user.id,
                bet_cell=payload.bet_cell,
                amount=payload.amount,
            )
        )
    else:
        existing_bet.amount += payload.amount

    db.commit()
    snapshot = _room_snapshot(db, user_id=user.id)
    db.commit()
    return snapshot


@router.get("/round/{round_id}")
def get_round(round_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    round_row = db.scalar(select(WheelPlusRound).where(WheelPlusRound.id == round_id))
    if round_row is None:
        raise HTTPException(status_code=404, detail="Round not found")
    return _format_round_payload(db, round_row)
