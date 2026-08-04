from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas import AdminActionPayload, AdminSearchPayload, InitDataPayload
from app.db.session import get_db
from app.services.admin_service import AdminService

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/dashboard")
def dashboard(payload: InitDataPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    AdminService.resolve_admin_user(db, payload.init_data)
    return AdminService.dashboard(db)


@router.post("/users/search")
def search_users(payload: AdminSearchPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    AdminService.resolve_admin_user(db, payload.init_data)
    return {"users": AdminService.search_users(db, payload.query, payload.limit)}


@router.post("/user/action")
def user_action(payload: AdminActionPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    actor, _ = AdminService.resolve_admin_user(db, payload.init_data)
    result = AdminService.apply_action(
        db,
        actor=actor,
        target_telegram_id=payload.telegram_id,
        action=payload.action,
        amount=payload.amount,
        role=payload.role,
        status=payload.status,
    )
    return result


@router.post("/audit")
def audit(payload: InitDataPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    AdminService.resolve_admin_user(db, payload.init_data)
    data = AdminService.dashboard(db)
    return {"audit": data.get("recent_actions", [])}
