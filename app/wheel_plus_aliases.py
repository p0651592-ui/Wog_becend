from __future__ import annotations

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import User, Wallet, WheelPlusBet
from app.db.session import get_db
from app.server import app, _ensure_user
from app.services.stats_service import StatsService
from app.services.wallet_service import WalletService
from app import wheel_plus_api as wpa


class WheelPlusRoomPayload(BaseModel):
    init_data: str = Field(default="")


class WheelPlusBetPayload(BaseModel):
    init_data: str = Field(default="")
    cell_key: str = Field(default="")
    amount: int = Field(gt=0)


class WheelPlusRevealPayload(BaseModel):
    init_data: str = Field(default="")
    round_id: int = Field(gt=0)


def _ensure_active_round(db: Session):
    room = wpa._ensure_room(db)
    current_round = wpa._ensure_round(db, room)
    if current_round.status != "settled" and wpa._current_seconds_remaining(current_round) <= 0:
        wpa._settle_round(db, room, current_round)
        db.commit()
        room = wpa._ensure_room(db)
        current_round = wpa._ensure_round(db, room)
    return room, current_round


@app.post("/api/wheel-plus/room")
def wheel_plus_room(payload: WheelPlusRoomPayload, db: Session = Depends(get_db)) -> dict:
    user, _ = _ensure_user(db, payload.init_data)
    room, current_round = _ensure_active_round(db)
    profile = StatsService.build_profile_payload(db, user)
    profile["text"] = StatsService.format_profile_text(profile)
    snapshot = WalletService.get_snapshot(db, user.id)
    room_payload = wpa._serialize_room(room, current_round)
    room_payload["player_total_bet"] = int(
        db.scalar(
            select(func.coalesce(func.sum(WheelPlusBet.amount), 0)).where(
                WheelPlusBet.round_id == current_round.id,
                WheelPlusBet.user_id == user.id,
            )
        )
        or 0
    )
    room_payload["players_count"] = int(
        db.scalar(
            select(func.count(func.distinct(WheelPlusBet.user_id))).where(WheelPlusBet.round_id == current_round.id)
        )
        or 0
    )
    room_payload["total_bet"] = int(
        db.scalar(select(func.coalesce(func.sum(WheelPlusBet.amount), 0)).where(WheelPlusBet.round_id == current_round.id))
        or 0
    )
    room_payload["total_payout"] = int(current_round.total_payout or 0)
    return {
        "status": "success",
        "balance": snapshot.balance,
        "profile": profile,
        "room": room_payload,
        "current_round": wpa._serialize_round(current_round),
        "recent_rounds": wpa._serialize_history(db, 12),
        "players": wpa._serialize_live_players(db, current_round.id),
        "cell_totals": wpa._serialize_cell_totals(db, current_round.id),
    }


@app.post("/api/wheel-plus/bet")
def wheel_plus_bet(payload: WheelPlusBetPayload, db: Session = Depends(get_db)) -> dict:
    user, _ = _ensure_user(db, payload.init_data)
    room, current_round = _ensure_active_round(db)
    cell_key = wpa._normalize_cell_key(payload.cell_key)

    if current_round.status != "betting" or wpa._current_seconds_remaining(current_round) <= 0:
        raise HTTPException(status_code=409, detail="Ставки уже закрыты")
    if cell_key not in {str(i) for i in range(37)} and cell_key not in wpa.CELL_LABELS:
        raise HTTPException(status_code=400, detail="Invalid bet cell")

    WalletService.place_bet(
        db,
        user.id,
        payload.amount,
        meta={"game": "wheel_plus", "room_id": room.id, "round_id": current_round.id, "cell_key": cell_key},
    )

    existing_bet = db.scalar(
        select(WheelPlusBet).where(
            WheelPlusBet.round_id == current_round.id,
            WheelPlusBet.user_id == user.id,
            WheelPlusBet.cell_key == cell_key,
        )
    )
    if existing_bet is None:
        existing_bet = WheelPlusBet(room_id=room.id, round_id=current_round.id, user_id=user.id, cell_key=cell_key, amount=0)
        db.add(existing_bet)
    existing_bet.amount += payload.amount
    db.flush()

    profile = StatsService.build_profile_payload(db, user)
    profile["text"] = StatsService.format_profile_text(profile)
    snapshot = WalletService.get_snapshot(db, user.id)
    db.commit()
    return {
        "status": "success",
        "balance": snapshot.balance,
        "profile": profile,
        "room": wheel_plus_room(WheelPlusRoomPayload(init_data=payload.init_data), db)["room"],
        "current_round": wpa._serialize_round(current_round),
        "recent_rounds": wpa._serialize_history(db, 12),
        "players": wpa._serialize_live_players(db, current_round.id),
        "cell_totals": wpa._serialize_cell_totals(db, current_round.id),
    }


@app.post("/api/wheel-plus/reveal")
def wheel_plus_reveal(payload: WheelPlusRevealPayload, db: Session = Depends(get_db)) -> dict:
    _ensure_user(db, payload.init_data)
    round_row = db.get(wpa.WheelPlusRound, payload.round_id)
    if round_row is None:
        raise HTTPException(status_code=404, detail="Round not found")

    if round_row.status != "settled":
        if round_row.betting_ends_at > wpa._utcnow():
            raise HTTPException(status_code=409, detail="Round is not settled yet")
        room = db.get(wpa.WheelPlusRoom, round_row.room_id)
        if room is None:
            raise HTTPException(status_code=404, detail="Room not found")
        wpa._settle_round(db, room, round_row)
        db.commit()

    return {
        "round": wpa._serialize_round(round_row),
        "fair": {
            "server_seed_hash": round_row.server_seed_hash,
            "server_seed": round_row.server_seed,
            "client_seed": round_row.client_seed,
            "nonce": round_row.nonce,
            "result_number": round_row.result_number,
            "result_color": round_row.result_color,
        },
    }


@app.post("/api/wheel-plus/settle")
def wheel_plus_settle(payload: WheelPlusRoomPayload, db: Session = Depends(get_db)) -> dict:
    _ensure_user(db, payload.init_data)
    room, current_round = _ensure_active_round(db)
    if current_round.status != "settled" and wpa._current_seconds_remaining(current_round) <= 0:
        wpa._settle_round(db, room, current_round)
        db.commit()
    return wheel_plus_room(payload, db)


@app.post("/api/wheel-plus/ping")
def wheel_plus_ping(payload: WheelPlusRoomPayload, db: Session = Depends(get_db)) -> dict:
    return wheel_plus_room(payload, db)
