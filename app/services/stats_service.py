from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PlayerStats, User, Wallet


class StatsService:
    @staticmethod
    def get_or_create(session: Session, user_id: int) -> PlayerStats:
        stats = session.scalar(select(PlayerStats).where(PlayerStats.user_id == user_id))
        if stats is None:
            stats = PlayerStats(user_id=user_id, max_balance=0)
            session.add(stats)
            session.flush()
        return stats

    @staticmethod
    def update_after_round(
        session: Session,
        user_id: int,
        bet: int,
        payout: int,
        multiplier: int,
    ) -> PlayerStats:
        stats = StatsService.get_or_create(session, user_id)
        wallet = session.scalar(select(Wallet).where(Wallet.user_id == user_id))
        user = session.scalar(select(User).where(User.id == user_id))

        stats.games_count += 1
        stats.total_bet += bet
        stats.total_volume += bet

        if payout > 0:
            stats.total_win += payout
            stats.today_win += payout
            stats.max_win = max(stats.max_win, payout)
        else:
            stats.total_loss += bet
            stats.today_loss += bet

        stats.max_multiplier = max(stats.max_multiplier, multiplier)
        if wallet is not None:
            stats.max_balance = max(stats.max_balance, wallet.balance)
        if user is not None:
            stats.last_game_at = user.updated_at
        return stats

    @staticmethod
    def build_profile_payload(session: Session, user: User) -> dict:
        wallet = session.scalar(select(Wallet).where(Wallet.user_id == user.id))
        stats = StatsService.get_or_create(session, user.id)
        balance = wallet.balance if wallet else 0
        stars = wallet.stars_balance if wallet else 0

        return {
            "telegram_id": user.telegram_id,
            "username": user.username or "noname",
            "first_name": user.first_name or "noname",
            "role": user.role,
            "status": user.status,
            "balance": balance,
            "stars": stars,
            "created_at": user.created_at.isoformat(),
            "games_count": stats.games_count,
            "today_win": stats.today_win,
            "today_loss": stats.today_loss,
            "total_volume": stats.total_volume,
            "max_balance": max(stats.max_balance, balance),
            "max_multiplier": stats.max_multiplier,
            "max_win": stats.max_win,
        }

    @staticmethod
    def format_profile_text(profile: dict) -> str:
        name = profile.get("username") or profile.get("first_name") or "noname"
        created_at = profile.get("created_at", "")[:10]
        return (
            f"📊 Игрок {name} 📊\n\n"
            f"💎 Баланс: {profile.get('balance', 0)} WC\n"
            f"⭐ Звёзды: {profile.get('stars', 0)}\n"
            f"🕓 Играет с {created_at}\n\n"
            f"📈 Выиграно сегодня: {profile.get('today_win', 0)} WC\n"
            f"📉 Проиграно сегодня: {profile.get('today_loss', 0)} WC\n"
            f"💰 Всего наиграно: {profile.get('total_volume', 0)} WC\n"
            f"💸 Наибольший баланс: {profile.get('max_balance', 0)} WC\n"
            f"🔥 Макс. коэффициент: {profile.get('max_multiplier', 0)}\n"
            f"🎉 Макс. выигрыш: {profile.get('max_win', 0)} WC"
        )
