import os
import sqlite3
import random
import hashlib
import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="WOG Casino Premium Backend")

# 🔔 НАСТРОЙКИ СВЯЗИ С ТЕЛЕГРАМ-ЧАТОМ ДЛЯ УВЕДОМЛЕНИЙ ОБ ОБНОВЛЕНИЯХ
TELEGRAM_BOT_TOKEN = "8804973603:AAHqWkyFQv8qW2ZZUHn7RSqVddqVCN6_vXs"  # Замени на токен твоего бота от @BotFather
TELEGRAM_CHAT_ID = "-1004438070296"     # Замени на ID твоей группы/чата (обязательно с минусом)

# НАСТРОЙКА КОРРЕКТНОЙ CORS-ПОЛИТИКИ ДЛЯ TELEGRAM MINI APP
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = "casino.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 100000
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            bet_type TEXT,
            amount INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

class PayoutSchema(BaseModel):
    user_id: int
    amount_won: int

@app.get("/status")
async def server_status():
    return {"status": "online", "engine": "FastAPI", "database": "SQLite3", "webhooks": "active"}

# 🚀 ЭНДПОИНТ ДЛЯ МГНОВЕННЫХ УВЕДОМЛЕНИЙ ОТ GITHUB WEBHOOK
@app.post("/github-webhook")
async def github_webhook(request: Request):
    try:
        payload = await request.json()
        if "commits" in payload:
            repo_name = payload["repository"]["name"]
            branch = payload["ref"].split("/")[-1]
            pusher = payload["pusher"]["name"]
            
            commit_messages = []
            for commit in payload["commits"]:
                author = commit["author"]["name"]
                message = commit["message"]
                commit_messages.append(f"• 👤 {author}: {message}")
            
            commits_text = "\n".join(commit_messages)
            
            tg_message = (
                f"🚀 *Новое обновление в репозитории!*\n\n"
                f"📁 *Репозиторий:* `{repo_name}`\n"
                f"🌿 *Ветка:* `{branch}`\n"
                f"🧑‍💻 *Автор пуша:* {pusher}\n\n"
                f"📝 *Список изменений:*\n{commits_text}"
            )
            
            url = f"https://telegram.org{TELEGRAM_BOT_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": tg_message, "parse_mode": "Markdown"})
            
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/user/balance/{user_id}")
async def get_user_balance(user_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row is None:
            cursor.execute("INSERT INTO users (user_id, username, balance) VALUES (?, ?, ?)", (user_id, "Wog_Player", 100000))
            conn.commit()
            balance = 100000
        else:
            balance = row[0]
        return {"user_id": user_id, "balance": balance, "status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.post("/api/wheel/payout")
async def process_payout(data: PayoutSchema):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (data.user_id,))
        row = cursor.fetchone()
        if row is None:
            cursor.execute("INSERT INTO users (user_id, username, balance) VALUES (?, ?, ?)", (data.user_id, "Wog_Player", data.amount_won))
        else:
            cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (data.amount_won, data.user_id))
        conn.commit()
        return {"status": "success", "balance": data.amount_won, "user_id": data.user_id}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
