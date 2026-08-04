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
from app.wheel_plus_live import admin_force_settle, get_room_snapshot, place_bet, reveal_round


class WheelPlusRoomPayload(BaseModel):
    init_data: str = Field(default="")


class WheelPlusBetPayload(BaseModel):
    init_data: str = Field(default="")
    cell_key: str = Field(default="")
    amount: int = Field(gt=0)


class WheelPlusRevealPayload(BaseModel):
    init_data: str = Field(default="")
    round_id: int = Field(gt=0)


def _live_players_and_cells(db: Session, round_id: int) -> tuple[list[dict], dict[str, int]]:
    rows = (
        db.execute(
            select(User, func.sum(WheelPlusBet.amount))
            .join(WheelPlusBet, WheelPlusBet.user_id == User.id)
            .where(WheelPlusBet.round_id == round_id)
            .group_by(User.id)
            .order_by(func.sum(WheelPlusBet.amount).desc())
        )
        .all()
    )
    players: list[dict] = []
    for user, amount in rows:
        wallet = db.scalar(select(Wallet).where(Wallet.user_id == user.id))
        cells = db.execute(
            select(WheelPlusBet.cell_key, func.sum(WheelPlusBet.amount))
            .where(WheelPlusBet.round_id == round_id, WheelPlusBet.user_id == user.id)
            .group_by(WheelPlusBet.cell_key)
        ).all()
        players.append(
            {
                "telegram_id": user.telegram_id,
                "username": user.username or user.first_name or "noname",
                "balance": wallet.balance if wallet else 0,
                "amount": int(amount or 0),
                "cells": [{"cell_key": key, "amount": int(total or 0)} for key, total in cells],
            }
        )
    totals = db.execute(
        select(WheelPlusBet.cell_key, func.sum(WheelPlusBet.amount))
        .where(WheelPlusBet.round_id == round_id)
        .group_by(WheelPlusBet.cell_key)
    ).all()
    cell_totals = {str(key): int(total or 0) for key, total in totals}
    return players, cell_totals


@app.post("/api/wheel-plus/room")
def wheel_plus_room(payload: WheelPlusRoomPayload, db: Session = Depends(get_db)) -> dict:
    user, _ = _ensure_user(db, payload.init_data)
    snapshot = get_room_snapshot(db)
    profile = StatsService.build_profile_payload(db, user)
    profile["text"] = StatsService.format_profile_text(profile)
    viewer_balance = WalletService.get_snapshot(db, user.id).balance
    live_players, cell_totals = _live_players_and_cells(db, snapshot["current_round"]["id"])
    snapshot["current_round"]["live_players"] = live_players
    snapshot["room"]["players_count"] = len(live_players)
    snapshot["room"]["player_total_bet"] = int(sum(player["amount"] for player in live_players))
    snapshot["room"]["total_bet"] = snapshot["room"].get("total_bet", snapshot["current_round"].get("total_bet", 0))
    snapshot["room"]["total_payout"] = snapshot["room"].get("total_payout", snapshot["current_round"].get("total_payout", 0))
    snapshot["players"] = live_players
    snapshot["cell_totals"] = cell_totals
    return {
        "status": "success",
        "balance": viewer_balance,
        "profile": profile,
        **snapshot,
    }


@app.post("/api/wheel-plus/bet")
def wheel_plus_bet(payload: WheelPlusBetPayload, db: Session = Depends(get_db)) -> dict:
    user, _ = _ensure_user(db, payload.init_data)
    result = place_bet(db, user, payload.cell_key.strip(), payload.amount)
    db.commit()
    snapshot = get_room_snapshot(db)
    live_players, cell_totals = _live_players_and_cells(db, snapshot["current_round"]["id"])
    profile = StatsService.build_profile_payload(db, user)
    profile["text"] = StatsService.format_profile_text(profile)
    viewer_balance = WalletService.get_snapshot(db, user.id).balance
    snapshot["current_round"]["live_players"] = live_players
    snapshot["players"] = live_players
    snapshot["cell_totals"] = cell_totals
    snapshot["room"]["players_count"] = len(live_players)
    snapshot["room"]["player_total_bet"] = int(sum(player["amount"] for player in live_players))
    snapshot["room"]["total_bet"] = int(sum(cell_totals.values()))
    snapshot["room"]["total_payout"] = snapshot["current_round"].get("total_payout", 0)
    return {
        "status": "success",
        "balance": viewer_balance,
        "profile": profile,
        "room": snapshot["room"],
        "current_round": snapshot["current_round"],
        "recent_rounds": snapshot["recent_rounds"],
        "players": live_players,
        "cell_totals": cell_totals,
    }


@app.post("/api/wheel-plus/reveal")
def wheel_plus_reveal(payload: WheelPlusRevealPayload, db: Session = Depends(get_db)) -> dict:
    _ensure_user(db, payload.init_data)
    return reveal_round(db, payload.round_id)


@app.post("/api/wheel-plus/settle")
def wheel_plus_settle(payload: WheelPlusRoomPayload, db: Session = Depends(get_db)) -> dict:
    _ensure_user(db, payload.init_data)
    return admin_force_settle(db)


@app.post("/api/wheel-plus/ping")
def wheel_plus_ping(payload: WheelPlusRoomPayload, db: Session = Depends(get_db)) -> dict:
    return wheel_plus_room(payload, db)
