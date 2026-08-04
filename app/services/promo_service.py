from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import PlayerStats, PromoCode, PromoRedemption, User
from app.services.wallet_service import WalletService


class PromoService:
    DEFAULT_PROMOS = (
        {
            "code": "WELCOME",
            "title": "Welcome bonus",
            "reward_balance": 1000,
            "reward_stars": 0,
            "max_uses": 999999,
        },
        {
            "code": "WOG2026",
            "title": "Launch bonus",
            "reward_balance": 5000,
            "reward_stars": 0,
            "max_uses": 10000,
        },
    )

    @staticmethod
    def seed_default_promos(session: Session) -> None:
        existing_count = session.scalar(select(func.count(PromoCode.id))) or 0
        if existing_count:
            return

        for payload in PromoService.DEFAULT_PROMOS:
            session.add(PromoCode(**payload))
        session.flush()

    @staticmethod
    def redeem(session: Session, user: User, raw_code: str) -> dict[str, object]:
        code = raw_code.strip().upper()
        if not code:
            raise ValueError("Промокод пуст")

        promo = session.scalar(
            select(PromoCode)
            .where(func.upper(PromoCode.code) == code)
            .with_for_update()
        )
        if promo is None:
            raise ValueError("Промокод не найден")
        if not promo.active:
            raise ValueError("Промокод отключён")
        if promo.expires_at and promo.expires_at <= datetime.now(timezone.utc):
            raise ValueError("Срок действия промокода истёк")
        if promo.used_count >= promo.max_uses:
            raise ValueError("Лимит активаций промокода исчерпан")

        already_redeemed = session.scalar(
            select(PromoRedemption).where(
                PromoRedemption.user_id == user.id,
                PromoRedemption.code == promo.code,
            )
        )
        if already_redeemed is not None:
            raise ValueError("Ты уже активировал этот промокод")

        snapshot = WalletService.get_snapshot(session, user.id)
        if promo.reward_balance > 0:
            snapshot = WalletService.deposit(
                session,
                user.id,
                promo.reward_balance,
                tx_type="promo",
                meta={"code": promo.code, "title": promo.title},
            )

        promo.used_count += 1
        session.add(
            PromoRedemption(
                promo_code_id=promo.id,
                user_id=user.id,
                code=promo.code,
                amount=promo.reward_balance,
            )
        )

        stats = session.scalar(select(PlayerStats).where(PlayerStats.user_id == user.id))
        if stats is not None:
            stats.max_balance = max(stats.max_balance, snapshot.balance)

        return {
            "code": promo.code,
            "title": promo.title,
            "reward_balance": promo.reward_balance,
            "reward_stars": promo.reward_stars,
            "balance": snapshot.balance,
        }
