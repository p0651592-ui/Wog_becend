# Wog_becend

WOG backend with Telegram Mini App auth, wallet, profile statistics, and a Telegram bot that shows player balance/profile in private chat.

## What is included

- FastAPI backend
- SQLAlchemy models for users, wallets, transactions, player stats, and game rounds
- Telegram Mini App initData verification
- Wallet service with atomic balance changes
- Player profile formatting for `/bal` and `/бал`
- Telegram bot with profile button and commands
- Dockerfile and docker-compose stack

## Main endpoints

- `GET /health`
- `POST /api/auth/telegram`
- `GET /api/profile/{telegram_id}`
- `POST /api/profile/me`
- `POST /api/user/balance`
- `POST /api/wheel/payout`
- `POST /api/games/round/finish`

## Local run

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

## Docker run

```bash
docker compose up --build
```

## Bot commands

- `/start`
- `/bal`
- `/бал`
- `/profile`
- `/top`

## Environment variables

Copy `.env.example` to `.env` and fill in:

- `BOT_TOKEN`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `DATABASE_URL`
- `CORS_ORIGINS`

