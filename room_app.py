from __future__ import annotations

# Import room models first so Base.metadata knows about them before startup.
from app.db import room_models  # noqa: F401
from app.api.wheel_plus_room import router as wheel_plus_router
from app.admin_main import app as app

app.include_router(wheel_plus_router)
