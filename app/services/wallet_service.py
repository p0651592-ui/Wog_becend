from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PlayerStats, Transaction, User, Wallet


@dataclass(slots=True)
class WalletSnapshot:
    balance: int
    stars_balance: int
    max_balance: int


class WalletService:
    STARTING_BALANCE = 0
    STARTING_STARS = 10

    @staticmethod
    def get_or_create_user(session: Session, telegram_id: int, username: str = "", first_name: str = "") -> User:
        user = session.scalar(select(User).where(User.telegram_id == telegram_id))
        if user is None:
            user = User(
                telegram_id=telegram_id,
                username=username or "",
                first_name=first_name or "noname",
                role="user",
                status="active",
            )
            session.add(user)
            session.flush()
            session.add(
                Wallet(
                    user_id=user.id,
                    balance=WalletService.STARTING_BALANCE,
                    stars_balance=WalletService.STARTING_STARS,
                    locked_balance=0,
                    max_balance=WalletService.STARTING_BALANCE,
                )
            )
            session.add(PlayerStats(user_id=user.id, max_balance=WalletService.STARTING_BALANCE))
            session.flush()
        else:
            if username:
                user.username = username
            if first_name:
                user.first_name = first_name
        return user

    @staticmethod
    def _get_wallet_for_update(session: Session, user_id: int) -> Wallet:
        wallet = session.scalar(select(Wallet).where(Wallet.user_id == user_id).with_for_update())
        if wallet is None:
            wallet = Wallet(user_id=user_id, balance=0, stars_balance=WalletService.STARTING_STARS, locked_balance=0, max_balance=0)
            session.add(wallet)
            session.flush()
        return wallet

    @staticmethod
    def _record_transaction(
        session: Session,
        user_id: int,
        tx_type: str,
        amount: int,
        balance_before: int,
        balance_after: int,
        meta: dict[str, Any] | None = None,
    ) -> None:
        session.add(
            Transaction(
                user_id=user_id,
                tx_type=tx_type,
                amount=amount,
                balance_before=balance_before,
                balance_after=balance_after,
                meta_json=(meta and __import__("json").dumps(meta, ensure_ascii=False)) or "{}",
            )
        )

    @staticmethod
    def get_snapshot(session: Session, user_id: int) -> WalletSnapshot:
        wallet = session.scalar(select(Wallet).where(Wallet.user_id == user_id))
        if wallet is None:
            return WalletSnapshot(balance=0, stars_balance=0, max_balance=0)
        return WalletSnapshot(balance=wallet.balance, stars_balance=wallet.stars_balance, max_balance=wallet.max_balance)

    @staticmethod
    def deposit(session: Session, user_id: int, amount: int, *, tx_type: str = "deposit", meta: dict[str, Any] | None = None) -> WalletSnapshot:
        if amount <= 0:
            raise ValueError("amount must be positive")
        wallet = WalletService._get_wallet_for_update(session, user_id)
        before = wallet.balance
        wallet.balance += amount
        wallet.max_balance = max(wallet.max_balance, wallet.balance)
        WalletService._record_transaction(session, user_id, tx_type, amount, before, wallet.balance, meta)
        return WalletSnapshot(balance=wallet.balance, stars_balance=wallet.stars_balance, max_balance=wallet.max_balance)

    @staticmethod
    def withdraw(session: Session, user_id: int, amount: int, *, tx_type: str = "withdraw", meta: dict[str, Any] | None = None) -> WalletSnapshot:
        if amount <= 0:
            raise ValueError("amount must be positive")
        wallet = WalletService._get_wallet_for_update(session, user_id)
        if wallet.balance < amount:
            raise ValueError("insufficient funds")
        before = wallet.balance
        wallet.balance -= amount
        WalletService._record_transaction(session, user_id, tx_type, -amount, before, wallet.balance, meta)
        return WalletSnapshot(balance=wallet.balance, stars_balance=wallet.stars_balance, max_balance=wallet.max_balance)

    @staticmethod
    def place_bet(session: Session, user_id: int, amount: int, *, meta: dict[str, Any] | None = None) -> WalletSnapshot:
        return WalletService.withdraw(session, user_id, amount, tx_type="bet", meta=meta)

    @staticmethod
    def payout(session: Session, user_id: int, amount: int, *, meta: dict[str, Any] | None = None) -> WalletSnapshot:
        return WalletService.deposit(session, user_id, amount, tx_type="win", meta=meta)
