import os
import sqlite3
import random
import hashlib
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="WOG Casino Backend")

# НАСТРОЙКА КОРРЕКТНОЙ CORS-ПОЛИТИКИ СЕРВЕРА FASTAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Полный доступ для любых WebApp-клиентов Telegram
    allow_credentials=False,  # СВЕРХВАЖНО: Меняем на False, чтобы убрать конфликт со звездочкой!
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
            balance INTEGER DEFAULT 5000
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            bet_cell TEXT,
            amount INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

class UserSyncSchema(BaseModel):
    user_id: int
    username: str
    local_balance: int

class BetSchema(BaseModel):
    user_id: int
    bet_cell: str
    amount: int

@app.post("/api/user/sync")
async def sync_user(data: UserSyncSchema):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (data.user_id,))
        row = cursor.fetchone()
        if row is None:
            cursor.execute(
                "INSERT INTO users (user_id, username, balance) VALUES (?, ?, ?)",
                (data.user_id, data.username, data.local_balance)
            )
            current_balance = data.local_balance
        else:
            current_balance = row[0]
        conn.commit()
        return {"status": "success", "balance": current_balance}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
@app.post("/api/wheel/bet")
async def place_bet(data: BetSchema):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        # Проверяем наличие пользователя и его текущий баланс
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (data.user_id,))
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=444, detail="User not found")
        
        current_balance = row[0]
        if current_balance < data.amount:
            raise HTTPException(status_code=400, detail="Insufficient funds")
        
        # Списываем сумму ставки с баланса пользователя
        new_balance = current_balance - data.amount
        cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, data.user_id))
        
        # Логируем ставку в таблицу истории
        cursor.execute(
            "INSERT INTO bets (user_id, bet_cell, amount) VALUES (?, ?, ?)",
            (data.user_id, data.bet_cell, data.amount)
        )
        
        conn.commit()
        return {"status": "success", "balance": new_balance}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

# ЭНДПОИНТ ДЛЯ НАЧИСЛЕНИЯ ВЫИГРЫШЕЙ ПОСЛЕ РАСЧЕТА РАУНДА
class PayoutSchema(BaseModel):
    user_id: int
    amount_won: int

@app.post("/api/wheel/payout")
async def process_payout(data: PayoutSchema):
    if data.amount_won <= 0:
        return {"status": "ignored", "message": "Payout amount must be positive"}
        
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (data.user_id,))
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=444, detail="User not found")
            
        new_balance = row[0] + data.amount_won
        cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, data.user_id))
        
        conn.commit()
        return {"status": "success", "balance": new_balance}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

# ТЕСТОВЫЙ ЭНДПОИНТ ПРОВЕРКИ СТАТУСА СЕРВЕРА
@app.get("/status")
async def server_status():
    return {"status": "online", "engine": "FastAPI", "language": "Python"}
