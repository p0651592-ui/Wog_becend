from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import User
from app.db.session import get_db
from app.services.telegram_auth import verify_telegram_init_data
from app.services.wheel_plus_service import build_state, place_bet, settle_due_round
from app.services.wallet_service import WalletService

router = APIRouter(prefix="/api/wheel-plus", tags=["wheel-plus"])


class WheelPlusStatePayload(BaseModel):
    init_data: str = Field(default="")


class WheelPlusBetPayload(BaseModel):
    init_data: str = Field(default="")
    cell_key: str = Field(default="")
    amount: int = Field(gt=0)


class WheelPlusSettlePayload(BaseModel):
    init_data: str = Field(default="")


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


@router.post("/state")
def state(payload: WheelPlusStatePayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = _ensure_user(db, payload.init_data)
    data = build_state(db, user, settle_if_due=True)
    db.commit()
    return data


@router.post("/bet")
def bet(payload: WheelPlusBetPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = _ensure_user(db, payload.init_data)
    try:
        data = place_bet(db, user, payload.cell_key, payload.amount)
        db.commit()
        return data
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/settle")
def settle(payload: WheelPlusSettlePayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = _ensure_user(db, payload.init_data)
    data = settle_due_round(db, user)
    db.commit()
    return data
