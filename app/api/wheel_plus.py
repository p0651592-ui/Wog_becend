from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import GameRound, PromoRedemption, User
from app.db.session import get_db
from app.services.stats_service import StatsService
from app.services.telegram_auth import verify_telegram_init_data
from app.services.wallet_service import WalletService
from app.services.wheel_plus_service import build_state, place_bet, settle_due_round

router = APIRouter(prefix="/api/wheel-plus", tags=["wheel-plus"])

AMERICAN_WHEEL_SEQUENCE = [
    "0", "28", "9", "26", "30", "11", "7", "20", "32", "17", "5", "22",
    "34", "15", "3", "24", "36", "13", "1", "00", "27", "10", "25", "29",
    "12", "8", "19", "31", "18", "6", "21", "33", "16", "4", "23", "35",
    "14", "2",
]

RED_NUMBERS = {"1", "3", "5", "7", "9", "12", "14", "16", "18", "19", "21", "23", "25", "27", "30", "32", "34", "36"}
BLACK_NUMBERS = {"2", "4", "6", "8", "10", "11", "13", "15", "17", "20", "22", "24", "26", "28", "29", "31", "33", "35"}
PROMO_REWARDS = {"wog2": 5_000_000, "wog_test": 50_000_000}


class WheelPlusStatePayload(BaseModel):
    init_data: str = Field(default="")


class WheelPlusBetPayload(BaseModel):
    init_data: str = Field(default="")
    cell_key: str = Field(default="")
    amount: int = Field(gt=0)


class WheelPlusSettlePayload(BaseModel):
    init_data: str = Field(default="")


class ClassicRouletteSpinPayload(BaseModel):
    init_data: str = Field(default="")
    bet: int = Field(gt=0)
    bet_type: str = Field(default="number")
    number: str = Field(default="0")
    client_seed: str = Field(default="")


class PromoRedeemPayload(BaseModel):
    init_data: str = Field(default="")
    code: str = Field(default="")


def _ensure_user(session: Session, init_data: str) -> User:
    if not settings.telegram_bot_token:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN is not configured")

    telegram_user = verify_telegram_init_data(init_data, settings.telegram_bot_token)
    if not telegram_user:
        raise HTTPException(status_code=403, detail="Telegram authentication failed")

    telegram_id = int(telegram_user["id"])
    username = str(telegram_user.get("username") or "")
    first_name = str(telegram_user.get("first_name") or telegram_user.get("last_name") or "noname")

    user = WalletService.get_or_create_user(session, telegram_id, username=username, first_name=first_name)
    session.flush()
    return user


def _roulette_color(value: str) -> str:
    if value in {"0", "00"}:
        return "green"
    if value in RED_NUMBERS:
        return "red"
    if value in BLACK_NUMBERS:
        return "black"
    return "green"


def _roulette_multiplier(bet_type: str, chosen_number: str, result: str) -> int:
    bet_type = bet_type.strip().lower()
    chosen_number = chosen_number.strip().upper()

    if bet_type == "number":
        return 35 if chosen_number == result else 0
    if bet_type in {"red", "black", "even", "odd", "low", "high"}:
        if result in {"0", "00"}:
            return 0
        number = int(result)
        if bet_type == "red" and result in RED_NUMBERS:
            return 1
        if bet_type == "black" and result in BLACK_NUMBERS:
            return 1
        if bet_type == "even" and number % 2 == 0:
            return 1
        if bet_type == "odd" and number % 2 == 1:
            return 1
        if bet_type == "low" and 1 <= number <= 18:
            return 1
        if bet_type == "high" and 19 <= number <= 36:
            return 1
    if bet_type in {"dozen1", "dozen2", "dozen3"}:
        if result in {"0", "00"}:
            return 0
        number = int(result)
        if bet_type == "dozen1" and 1 <= number <= 12:
            return 2
        if bet_type == "dozen2" and 13 <= number <= 24:
            return 2
        if bet_type == "dozen3" and 25 <= number <= 36:
            return 2
    if bet_type in {"column1", "column2", "column3"}:
        if result in {"0", "00"}:
            return 0
        number = int(result)
        column = ((number - 1) % 3) + 1
        if (bet_type == "column1" and column == 1) or (bet_type == "column2" and column == 2) or (bet_type == "column3" and column == 3):
            return 2
    return 0


def _classic_result(server_seed: str, client_seed: str, nonce: int) -> str:
    digest = hmac.new(
        server_seed.encode("utf-8"),
        f"{client_seed}:{nonce}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    index = int.from_bytes(digest[:8], "big") % len(AMERICAN_WHEEL_SEQUENCE)
    return AMERICAN_WHEEL_SEQUENCE[index]


@app.post("/state")
def state(payload: WheelPlusStatePayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = _ensure_user(db, payload.init_data)
    data = build_state(db, user, settle_if_due=True)
    db.commit()
    return data


@app.post("/bet")
def bet(payload: WheelPlusBetPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = _ensure_user(db, payload.init_data)
    try:
        data = place_bet(db, user, payload.cell_key, payload.amount)
        db.commit()
        return data
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/settle")
def settle(payload: WheelPlusSettlePayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = _ensure_user(db, payload.init_data)
    data = settle_due_round(db, user)
    db.commit()
    return data


@app.post("/classic/spin")
def classic_spin(payload: ClassicRouletteSpinPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = _ensure_user(db, payload.init_data)

    bet_amount = int(payload.bet)
    if bet_amount <= 0:
        raise HTTPException(status_code=400, detail="Bet must be positive")

    client_seed = payload.client_seed.strip() or f"wheel-{user.telegram_id}"
    server_seed = secrets.token_hex(32)
    server_seed_hash = hashlib.sha256(server_seed.encode("utf-8")).hexdigest()
    nonce = secrets.randbelow(1_000_000)

    try:
        WalletService.place_bet(
            db,
            user.id,
            bet_amount,
            meta={"game": "wheel_classic", "bet_type": payload.bet_type, "number": payload.number, "client_seed": client_seed},
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = _classic_result(server_seed, client_seed, nonce)
    multiplier = _roulette_multiplier(payload.bet_type, payload.number, result)
    payout = bet_amount * multiplier if multiplier > 0 else 0

    if payout > 0:
        WalletService.payout(db, user.id, payout, meta={"game": "wheel_classic", "result": result, "client_seed": client_seed})

    round_row = GameRound(
        user_id=user.id,
        game_type="wheel_classic",
        bet=bet_amount,
        payout=payout,
        multiplier=multiplier,
        client_seed=client_seed,
        server_seed_hash=server_seed_hash,
        server_seed=server_seed,
        nonce=nonce,
        result_json=json.dumps(
            {
                "result": result,
                "color": _roulette_color(result),
                "bet_type": payload.bet_type,
                "chosen_number": payload.number,
                "client_seed": client_seed,
                "server_seed_hash": server_seed_hash,
                "nonce": nonce,
                "payout": payout,
                "multiplier": multiplier,
            },
            ensure_ascii=False,
        ),
    )
    db.add(round_row)
    StatsService.update_after_round(db, user.id, bet=bet_amount, payout=payout, multiplier=multiplier)
    db.commit()

    profile = StatsService.build_profile_payload(db, user)
    profile["text"] = StatsService.format_profile_text(profile)
    snapshot = WalletService.get_snapshot(db, user.id)
    return {
        "status": "success",
        "game": "wheel_classic",
        "result": result,
        "color": _roulette_color(result),
        "balance": snapshot.balance,
        "payout": payout,
        "multiplier": multiplier,
        "profile": profile,
        "round": {
            "id": round_row.id,
            "bet": bet_amount,
            "bet_type": payload.bet_type,
            "chosen_number": payload.number,
            "client_seed": client_seed,
            "server_seed_hash": server_seed_hash,
            "server_seed": server_seed,
            "nonce": nonce,
        },
    }


@app.post("/promo/redeem")
def redeem_promo(payload: PromoRedeemPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = _ensure_user(db, payload.init_data)
    code = payload.code.strip().lower()
    if not code:
        raise HTTPException(status_code=400, detail="Enter a promo code")

    if code not in PROMO_REWARDS:
        raise HTTPException(status_code=404, detail="Unknown promo code")

    already_claimed = db.scalar(
        select(PromoRedemption).where(PromoRedemption.user_id == user.id, PromoRedemption.code == code)
    )
    if already_claimed is not None:
        raise HTTPException(status_code=400, detail="Promo code already used")

    amount = PROMO_REWARDS[code]
    WalletService.deposit(db, user.id, amount, tx_type="promo_bonus", meta={"code": code, "source": "startup"})
    db.add(PromoRedemption(user_id=user.id, code=code, amount=amount))
    db.commit()

    profile = StatsService.build_profile_payload(db, user)
    profile["text"] = StatsService.format_profile_text(profile)
    return {
        "status": "success",
        "code": code,
        "amount": amount,
        "balance": profile.get("balance", 0),
        "profile": profile,
    }
