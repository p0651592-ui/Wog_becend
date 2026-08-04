from app.main import app  # noqa: F401
from app import wheel_plus_routes  # noqa: F401


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
