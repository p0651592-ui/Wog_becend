import os
import sqlite3
import hmac
import hashlib
import json
import requests
from urllib.parse import parse_qsl
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="WOG Casino Secured Backend")

# 🔔 Настройки Telegram
TELEGRAM_BOT_TOKEN = "8804973603:AAHqWkyFQv8qW2ZZUHn7RSqVddqVCN6_vXs"
TELEGRAM_CHAT_ID = "-1004438070296"

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
DB_FILE = "casino.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 100000)")
    conn.commit()
    conn.close()

init_db()

# --- ВАЛИДАЦИЯ ---
def verify_telegram_data(init_data: str, token: str) -> dict | bool:
    try:
        vals = dict(parse_qsl(init_data))
        if "hash" not in vals: return False
        tg_hash = vals.pop("hash")
        data_check_string = "\n".join([f"{k}={v}" for k, v in sorted(vals.items())])
        secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        if hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest() == tg_hash:
            return json.loads(vals["user"])
        return False
    except: return False

class GameRequest(BaseModel):
    init_data: str
    amount_won: int = 0

# --- ЭНДПОИНТЫ ---
@app.post("/github-webhook")
async def github_webhook(request: Request):
    # Логика отправки уведомлений в ТГ (api.telegram.org)
    payload = await request.json()
    # ... логика обработки коммитов ...
    url = f"https://telegram.org{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": "Обновление", "parse_mode": "Markdown"})
    return {"status": "success"}

@app.post("/api/user/balance")
async def get_user_balance(data: GameRequest):
    user_data = verify_telegram_data(data.init_data, TELEGRAM_BOT_TOKEN)
    if not user_data: raise HTTPException(status_code=403)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_data["id"],))
    row = cursor.fetchone()
    if row is None:
        cursor.execute("INSERT INTO users (user_id, username, balance) VALUES (?, ?, 100000)", (user_data["id"], user_data.get("username", "Player")))
        conn.commit()
        balance = 100000
    else: balance = row[0]
    conn.close()
    return {"balance": balance}

@app.post("/api/wheel/payout")
async def process_payout(data: GameRequest):
    user_data = verify_telegram_data(data.init_data, TELEGRAM_BOT_TOKEN)
    if not user_data: raise HTTPException(status_code=403)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # ИСПРАВЛЕНО: Прибавление выигрыша, а не замена
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (data.amount_won, user_data["id"]))
    conn.commit()
    conn.close()
    return {"status": "success"}
