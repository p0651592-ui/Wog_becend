from __future__ import annotations

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.server import app, _ensure_user
from app.wheel_plus_api import _serialize_round, _settle_round, _ensure_room, _ensure_round
from app import wheel_plus_api as wpa


class WheelPlusRoomPayload(BaseModel):
    init_data: str = Field(default="")


class WheelPlusRevealPayload(BaseModel):
    init_data: str = Field(default="")
    round_id: int = Field(gt=0)


@app.post("/api/wheel-plus/room")
def wheel_plus_room(payload: WheelPlusRoomPayload, db: Session = Depends(get_db)) -> dict:
    return wpa.wheel_plus_state(wpa.WheelPlusRoomPayload(init_data=payload.init_data), db)


@app.post("/api/wheel-plus/reveal")
def wheel_plus_reveal(payload: WheelPlusRevealPayload, db: Session = Depends(get_db)) -> dict:
    _ensure_user(db, payload.init_data)
    round_row = db.get(wpa.WheelPlusRound, payload.round_id)
    if round_row is None:
        raise HTTPException(status_code=404, detail="Round not found")

    if round_row.status != "settled":
        room = db.get(wpa.WheelPlusRoom, round_row.room_id)
        if room is None:
            raise HTTPException(status_code=404, detail="Room not found")
        if round_row.betting_ends_at > wpa._utcnow():
            raise HTTPException(status_code=409, detail="Round is not settled yet")
        settled = _settle_round(db, room, round_row)
        db.commit()
        round_row = db.get(wpa.WheelPlusRound, settled["id"]) if isinstance(settled, dict) else round_row
        if round_row is None:
            round_row = db.get(wpa.WheelPlusRound, payload.round_id)

    return {
        "round": _serialize_round(round_row),
        "fair": {
            "server_seed_hash": round_row.server_seed_hash,
            "server_seed": round_row.server_seed,
            "client_seed": round_row.client_seed,
            "nonce": round_row.nonce,
            "result_number": round_row.result_number,
            "result_color": round_row.result_color,
        },
    }


@app.post("/api/wheel-plus/admin/force-settle")
def wheel_plus_admin_force_settle(payload: WheelPlusRoomPayload, db: Session = Depends(get_db)) -> dict:
    _ensure_user(db, payload.init_data)
    room = _ensure_room(db)
    current_round = _ensure_round(db, room)
    if current_round.status != "settled" and current_round.betting_ends_at <= wpa._utcnow():
        _settle_round(db, room, current_round)
        db.commit()
    return wpa.wheel_plus_state(wpa.WheelPlusRoomPayload(init_data=payload.init_data), db)
