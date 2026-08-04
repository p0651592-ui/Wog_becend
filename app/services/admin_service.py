from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import String, cast, desc, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AdminAuditLog, GameRound, PlayerStats, Transaction, User, Wallet
from app.services.telegram_auth import verify_telegram_init_data
from app.services.wallet_service import WalletService


class AdminService:
    @staticmethod
    def promote_if_admin(user: User) -> User:
        if user.telegram_id in settings.admin_telegram_ids:
            user.role = "owner" if settings.admin_telegram_ids and user.telegram_id == settings.admin_telegram_ids[0] else "admin"
        return user

    @staticmethod
    def is_admin(user: User) -> bool:
        return user.role in {"admin", "owner"} or user.telegram_id in settings.admin_telegram_ids

    @staticmethod
    def resolve_admin_user(session: Session, init_data: str) -> tuple[User, dict[str, Any]]:
        telegram_user = verify_telegram_init_data(init_data, settings.telegram_bot_token)
        if not telegram_user:
            raise HTTPException(status_code=403, detail="Telegram authentication failed")

        telegram_id = int(telegram_user["id"])
        username = str(telegram_user.get("username") or "")
        first_name = str(telegram_user.get("first_name") or telegram_user.get("last_name") or "noname")

        user = WalletService.get_or_create_user(session, telegram_id, username=username, first_name=first_name)
        AdminService.promote_if_admin(user)
        session.flush()

        if not AdminService.is_admin(user):
            raise HTTPException(status_code=403, detail="Admin access required")

        return user, telegram_user

    @staticmethod
    def log_action(
        session: Session,
        actor_user_id: int | None,
        target_user_id: int | None,
        action: str,
        amount: int = 0,
        meta: dict[str, Any] | None = None,
    ) -> None:
        session.add(
            AdminAuditLog(
                actor_user_id=actor_user_id,
                target_user_id=target_user_id,
                action=action,
                amount=amount,
                meta_json=json.dumps(meta or {}, ensure_ascii=False),
            )
        )

    @staticmethod
    def dashboard(session: Session) -> dict[str, Any]:
        users_total = session.scalar(select(func.count(User.id))) or 0
        admins_total = session.scalar(select(func.count(User.id)).where(User.role.in_(["admin", "owner"]))) or 0
        blocked_total = session.scalar(select(func.count(User.id)).where(User.status == "blocked")) or 0
        wallets_total = session.scalar(select(func.coalesce(func.sum(Wallet.balance), 0))) or 0
        stars_total = session.scalar(select(func.coalesce(func.sum(Wallet.stars_balance), 0))) or 0
        transactions_total = session.scalar(select(func.count(Transaction.id))) or 0
        rounds_total = session.scalar(select(func.count(GameRound.id))) or 0
        top_balance = session.scalar(select(func.coalesce(func.max(Wallet.balance), 0))) or 0
        top_stars = session.scalar(select(func.coalesce(func.max(Wallet.stars_balance), 0))) or 0

        recent_users = session.execute(
            select(User, Wallet, PlayerStats)
            .join(Wallet, Wallet.user_id == User.id)
            .join(PlayerStats, PlayerStats.user_id == User.id)
            .order_by(desc(User.created_at))
            .limit(10)
        ).all()

        top_players = session.execute(
            select(User, Wallet, PlayerStats)
            .join(Wallet, Wallet.user_id == User.id)
            .join(PlayerStats, PlayerStats.user_id == User.id)
            .order_by(desc(Wallet.balance), desc(PlayerStats.total_volume))
            .limit(10)
        ).all()

        recent_actions = session.execute(
            select(AdminAuditLog)
            .order_by(desc(AdminAuditLog.created_at))
            .limit(10)
        ).scalars().all()

        return {
            "summary": {
                "users_total": users_total,
                "admins_total": admins_total,
                "blocked_total": blocked_total,
                "wallets_total": wallets_total,
                "stars_total": stars_total,
                "transactions_total": transactions_total,
                "rounds_total": rounds_total,
                "top_balance": top_balance,
                "top_stars": top_stars,
            },
            "recent_users": [AdminService._serialize_user_row(row) for row in recent_users],
            "top_players": [AdminService._serialize_user_row(row) for row in top_players],
            "recent_actions": [AdminService._serialize_audit(row) for row in recent_actions],
        }

    @staticmethod
    def search_users(session: Session, query: str, limit: int = 20) -> list[dict[str, Any]]:
        search = query.strip()
        stmt = (
            select(User, Wallet, PlayerStats)
            .join(Wallet, Wallet.user_id == User.id)
            .join(PlayerStats, PlayerStats.user_id == User.id)
        )
        if search:
            like = f"%{search}%"
            stmt = stmt.where(
                or_(
                    User.username.ilike(like),
                    User.first_name.ilike(like),
                    cast(User.telegram_id, String).ilike(like),
                )
            )
        stmt = stmt.order_by(desc(User.created_at)).limit(max(1, min(limit, 50)))
        rows = session.execute(stmt).all()
        return [AdminService._serialize_user_row(row) for row in rows]

    @staticmethod
    def apply_action(
        session: Session,
        actor: User,
        target_telegram_id: int,
        action: str,
        amount: int = 0,
        role: str = "",
        status: str = "",
    ) -> dict[str, Any]:
        target = session.scalar(select(User).where(User.telegram_id == target_telegram_id))
        if target is None:
            raise HTTPException(status_code=404, detail="Target user not found")

        action_name = action.strip().lower()
        meta: dict[str, Any] = {"actor": actor.telegram_id, "target": target.telegram_id, "action": action_name}

        if action_name in {"bonus", "grant"}:
            if amount <= 0:
                raise HTTPException(status_code=400, detail="Amount must be positive")
            snapshot = WalletService.deposit(session, target.id, amount, tx_type="admin_bonus", meta=meta)
            AdminService._sync_stats_max_balance(session, target.id, snapshot.balance)
            AdminService.log_action(session, actor.id, target.id, "bonus", amount, meta)
            session.commit()
            return {"status": "ok", "balance": snapshot.balance}

        if action_name in {"deduct", "take"}:
            if amount <= 0:
                raise HTTPException(status_code=400, detail="Amount must be positive")
            snapshot = WalletService.withdraw(session, target.id, amount, tx_type="admin_deduct", meta=meta)
            AdminService.log_action(session, actor.id, target.id, "deduct", amount, meta)
            session.commit()
            return {"status": "ok", "balance": snapshot.balance}

        if action_name == "block":
            target.status = "blocked"
            AdminService.log_action(session, actor.id, target.id, "block", amount, meta)
            session.commit()
            return {"status": "ok", "user_status": target.status}

        if action_name == "unblock":
            target.status = "active"
            AdminService.log_action(session, actor.id, target.id, "unblock", amount, meta)
            session.commit()
            return {"status": "ok", "user_status": target.status}

        if action_name == "role":
            normalized_role = role.strip().lower()
            if normalized_role not in {"user", "moderator", "admin", "owner"}:
                raise HTTPException(status_code=400, detail="Invalid role")
            if normalized_role == "owner" and actor.role != "owner":
                raise HTTPException(status_code=403, detail="Only owner can assign owner role")
            target.role = normalized_role
            AdminService.log_action(session, actor.id, target.id, "role", 0, {**meta, "role": normalized_role})
            session.commit()
            return {"status": "ok", "role": target.role}

        raise HTTPException(status_code=400, detail="Unsupported admin action")

    @staticmethod
    def _sync_stats_max_balance(session: Session, user_id: int, balance: int) -> None:
        stats = session.scalar(select(PlayerStats).where(PlayerStats.user_id == user_id))
        if stats is not None:
            stats.max_balance = max(stats.max_balance, balance)

    @staticmethod
    def _serialize_user_row(row: tuple[User, Wallet, PlayerStats]) -> dict[str, Any]:
        user, wallet, stats = row
        return {
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
            "role": user.role,
            "status": user.status,
            "balance": wallet.balance if wallet else 0,
            "stars_balance": wallet.stars_balance if wallet else 0,
            "games_count": stats.games_count if stats else 0,
            "total_volume": stats.total_volume if stats else 0,
            "total_win": stats.total_win if stats else 0,
            "total_loss": stats.total_loss if stats else 0,
            "today_win": stats.today_win if stats else 0,
            "today_loss": stats.today_loss if stats else 0,
            "max_balance": stats.max_balance if stats else 0,
            "max_multiplier": stats.max_multiplier if stats else 0,
            "max_win": stats.max_win if stats else 0,
            "created_at": user.created_at.isoformat(),
            "updated_at": user.updated_at.isoformat(),
        }

    @staticmethod
    def _serialize_audit(log: AdminAuditLog) -> dict[str, Any]:
        return {
            "id": log.id,
            "actor_user_id": log.actor_user_id,
            "target_user_id": log.target_user_id,
            "action": log.action,
            "amount": log.amount,
            "meta": json.loads(log.meta_json or "{}"),
            "created_at": log.created_at.isoformat(),
        }
