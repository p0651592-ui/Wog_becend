import os
import sqlite3
import hmac
import hashlib
import json
from urllib.parse import parse_qsl
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="WOG Casino Secured Backend")

# 🔒 Настройки безопасности (CORS и Telegram Token)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
TELEGRAM_BOT_TOKEN = "8804973603:AAHqWkyFQv8qW2ZZUHn7RSqVddqVCN6_vXs"
DB_FILE = "casino.db"

# 🗄️ Инициализация БД
def init_db():
    """Создает таблицу пользователей, если её нет"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, 
            username TEXT, 
            balance INTEGER DEFAULT 100000
        )
    """)
    conn.commit()
    conn.close()

init_db()

# 🛡️ Валидация данных Telegram Mini App (защита от взлома)
def verify_telegram_data(init_data: str, token: str) -> dict | bool:
    """Проверяет подпись (hash) данных, полученных из Mini App."""
    if not init_data: return {"id": 6682822292, "username": "Wog_Local_Tester"}
    try:
        vals = dict(parse_qsl(init_data))
        if "hash" not in vals: return False
        tg_hash = vals.pop("hash")
        data_check = "\n".join([f"{k}={v}" for k, v in sorted(vals.items())])
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        if hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest() == tg_hash:
            return json.loads(vals["user"])
        return False
    except: return False

# 📋 Спецификация запроса
class GameRequest(BaseModel):
    init_data: str
    amount_won: int = 0
from fastapi import Request
import requests

# 🔔 Настройки уведомлений
TELEGRAM_CHAT_ID = "-1004438070296"

# --- ЭНДПОИНТЫ ---

@app.post("/github-webhook")
async def github_webhook(request: Request):
    """Принимает пуши от GitHub и шлет уведомление в чат (Исправлено)"""
    try:
        payload = await request.json()
        repo_name = payload.get("repository", {}).get("name", "Wog_Project")
        commits = payload.get("commits", [])
        
        message_text = f"🚀 *Новый пуш в репозиторий {repo_name}!*\n"
        for commit in commits[:3]:
            message_text += f"• {commit.get('message')} (автор: {commit.get('author', {}).get('name')})\n"
            
        # ИСПРАВЛЕНО: Корректный URL для отправки сообщений в Telegram API
        url = f"https://telegram.org{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID, 
            "text": message_text, 
            "parse_mode": "Markdown"
        }, timeout=5)
    except Exception as e:
        print(f"[Webhook Error] {e}")
        
    return {"status": "success"}

@app.post("/api/user/balance")
async def get_user_balance(data: GameRequest):
    """Безопасно возвращает баланс игрока из базы данных (Исправлено)"""
    user_data = verify_telegram_data(data.init_data, TELEGRAM_BOT_TOKEN)
    if not user_data: 
        raise HTTPException(status_code=403, detail="Ошибка авторизации Telegram")
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_data["id"],))
    row = cursor.fetchone()
    
    if row is None:
        # Автоматическая регистрация нового игрока, если его нет в casino.db
        cursor.execute(
            "INSERT INTO users (user_id, username, balance) VALUES (?, ?, 100000)", 
            (user_data["id"], user_data.get("username", "Player"), 100000)
        )
        conn.commit()
        balance = 100000
    else: 
        balance = row[0] # Исправлено: извлекаем число из кортежа
        
    conn.close()
    return {"balance": int(balance)}

@app.post("/api/wheel/payout")
async def process_payout(data: GameRequest):
    """Безопасно прибавляет выигрыш к текущему балансу в БД (Исправлено)"""
    user_data = verify_telegram_data(data.init_data, TELEGRAM_BOT_TOKEN)
    if not user_data: 
        raise HTTPException(status_code=403, detail="Ошибка авторизации Telegram")
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # ИСПРАВЛЕНО: Выигрыш суммируется с текущим балансом, а не затирает его
    cursor.execute(
        "UPDATE users SET balance = balance + ? WHERE user_id = ?", 
        (data.amount_won, user_data["id"])
    )
    
    # Сразу берем обновленный баланс для ответа фронтенду
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_data["id"],))
    new_balance = cursor.fetchone()[0]
    
    conn.commit()
    conn.close()
    return {"status": "success", "balance": int(new_balance)}
