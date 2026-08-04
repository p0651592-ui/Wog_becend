# Wog_becend

WOG backend with Telegram Mini App auth, wallet, profile statistics, Wheel Classic server spin, and a Telegram bot that shows player balance/profile in private chat.

## What is included

- FastAPI backend
- SQLAlchemy models for users, wallets, transactions, player stats, game rounds, and admin audit logs
- Telegram Mini App initData verification
- Wallet service with atomic balance changes
- Player profile formatting for `/bal` and `/бал`
- Server-side Wheel Classic roulette spin with payouts and round history
- Telegram bot with profile button and commands
- Admin panel at `/admin` for dashboard, search, roles, block/unblock, and bonuses
- Dockerfile and docker-compose stack

## Main endpoints

- `GET /health`
- `GET /admin`
- `POST /api/auth/telegram`
- `GET /api/profile/{telegram_id}`
- `POST /api/profile/me`
- `POST /api/user/balance`
- `POST /api/wheel/payout`
- `POST /api/wheel-classic/spin`
- `POST /api/games/round/finish`
- `POST /api/admin/dashboard`
- `POST /api/admin/users/search`
- `POST /api/admin/user/action`
- `POST /api/admin/audit`

## Local run

```bash
pip install -r requirements.txt
uvicorn app.admin_main:app --reload
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
- `ADMIN_TELEGRAM_IDS`
- `DATABASE_URL`
- `CORS_ORIGINS`

