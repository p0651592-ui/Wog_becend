from __future__ import annotations

import json
import logging
from typing import Any

import requests
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import BalancePayload, GameRoundPayload, InitDataPayload, PayoutPayload
from app.core.config import settings
from app.db.base import Base
from app.db.models import GameRound, User
from app.db.session import engine, get_db
from app.services.stats_service import StatsService
from app.services.telegram_auth import verify_telegram_init_data
from app.services.wallet_service import WalletService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("wog.backend")

app = FastAPI(title=settings.project_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.cors_origins == ["*"] else settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


def _ensure_user(session: Session, init_data: str) -> tuple[User, dict[str, Any]]:
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
    return user, telegram_user


@app.get("/")
def root() -> dict[str, Any]:
    return {"status": "ok", "service": settings.project_name}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/api/auth/telegram")
def auth_telegram(payload: InitDataPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = _ensure_user(db, payload.init_data)
    db.commit()
    profile = StatsService.build_profile_payload(db, user)
    profile["text"] = StatsService.format_profile_text(profile)
    return profile


@app.get("/api/profile/{telegram_id}")
def get_profile_by_telegram_id(telegram_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = db.scalar(select(User).where(User.telegram_id == telegram_id))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    profile = StatsService.build_profile_payload(db, user)
    profile["text"] = StatsService.format_profile_text(profile)
    return profile


@app.post("/api/profile/me")
def get_my_profile(payload: InitDataPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = _ensure_user(db, payload.init_data)
    profile = StatsService.build_profile_payload(db, user)
    profile["text"] = StatsService.format_profile_text(profile)
    return profile


@app.post("/api/user/balance")
def get_user_balance(payload: BalancePayload, db: Session = Depends(get_db)) -> dict[str, int]:
    user, _ = _ensure_user(db, payload.init_data)
    db.commit()
    snapshot = WalletService.get_snapshot(db, user.id)
    return {"balance": snapshot.balance}


@app.post("/api/wheel/payout")
def process_payout(payload: PayoutPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = _ensure_user(db, payload.init_data)
    snapshot = WalletService.payout(db, user.id, payload.amount_won, meta={"source": "wheel"})
    StatsService.update_after_round(db, user.id, bet=0, payout=payload.amount_won, multiplier=0)
    db.commit()
    profile = StatsService.build_profile_payload(db, user)
    profile["balance"] = snapshot.balance
    profile["text"] = StatsService.format_profile_text(profile)
    return {"status": "success", "balance": snapshot.balance, "profile": profile}


@app.post("/api/games/round/finish")
def finish_game_round(payload: GameRoundPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = _ensure_user(db, payload.init_data)

    if payload.bet > 0:
        WalletService.place_bet(db, user.id, payload.bet, meta={"game": payload.game_type})
    if payload.payout > 0:
        WalletService.payout(db, user.id, payload.payout, meta={"game": payload.game_type})

    round_row = GameRound(
        user_id=user.id,
        game_type=payload.game_type,
        bet=payload.bet,
        payout=payload.payout,
        multiplier=payload.multiplier,
        client_seed=payload.client_seed,
        server_seed_hash=payload.server_seed_hash,
        server_seed=payload.server_seed,
        nonce=payload.nonce,
        result_json=json.dumps(payload.result_json, ensure_ascii=False),
    )
    db.add(round_row)
    StatsService.update_after_round(db, user.id, bet=payload.bet, payout=payload.payout, multiplier=payload.multiplier)
    db.commit()

    profile = StatsService.build_profile_payload(db, user)
    profile["text"] = StatsService.format_profile_text(profile)
    return {
        "status": "success",
        "game_id": round_row.id,
        "profile": profile,
        "round": {
            "bet": payload.bet,
            "payout": payload.payout,
            "multiplier": payload.multiplier,
            "client_seed": payload.client_seed,
            "server_seed_hash": payload.server_seed_hash,
            "nonce": payload.nonce,
        },
    }


@app.post("/github-webhook")
async def github_webhook(request: Request) -> dict[str, str]:
    try:
        payload = await request.json()
        repo_name = payload.get("repository", {}).get("full_name") or payload.get("repository", {}).get("name", "Wog_Project")
        commits = payload.get("commits", [])
        lines = []
        for commit in commits[:5]:
            lines.append(f"• {commit.get('message')} (автор: {commit.get('author', {}).get('name')})")

        if settings.telegram_bot_token and settings.telegram_chat_id:
            message_text = f"🚀 Новый пуш в {repo_name}\n\n" + "\n".join(lines)
            requests.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                json={
                    "chat_id": settings.telegram_chat_id,
                    "text": message_text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
    except Exception as exc:  # pragma: no cover - webhook should never break app
        logger.exception("GitHub webhook failed: %s", exc)
    return {"status": "success"}
