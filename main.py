import os
import random
from typing import Optional
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="WOG Casino Core Engine")

# НАСТРОЙКА CORS ДЛЯ БЕЗОПАСНОГО КОННЕКТА С GITHUB PAGES
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Разрешаем запросы со всех фронтендов
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Глобальная база данных игроков и промокодов в оперативной памяти Python
db = {
    "users": {},
    "promos": {}
}

OWNER_ID = 6682822292  # Ваш ID Администратора

# --- МОДЕЛИ ДАННЫХ ДЛЯ ЗАПРОСОВ (PYDANTIC) ---
class UserLogin(BaseModel):
    id: int
    first_name: Optional[str] = "Игрок"
    username: Optional[str] = ""
    photo_url: Optional[str] = ""
    auth_data: Optional[str] = ""

class BalanceUpdate(BaseModel):
    id: int
    amount: int

# --- ЭНДПОИНТ 1: АВТОРИЗАЦИЯ И РЕГИСТРАЦИЯ ИГРОКА ---
@app.post("/api/user")
async def login_user(user_data: UserLogin):
    user_id = user_data.id
    
    # Принудительная авторизация создателя, если Telegram заблокировал данные
    if not user_id or user_id == OWNER_ID:
        user_id = OWNER_ID
        user_data.first_name = "Основатель (WOG)"
        user_data.username = "FounderAdmin"

    assigned_role = "admin" if user_id == OWNER_ID else "user"

    # Если игрока нет в оперативной памяти — регистрируем с начальным балансом 5000 W
    if user_id not in db["users"]:
        db["users"][user_id] = {
            "id": user_id,
            "name": user_data.first_name,
            "username": user_data.username,
            "photo_url": user_data.photo_url,
            "balance": 5000,
            "role": assigned_role
        }
    else:
        # Если игрок уже есть, просто обновляем его данные из Telegram сессии
        db["users"][user_id]["name"] = user_data.first_name or db["users"][user_id]["name"]
        db["users"][user_id]["username"] = user_data.username or db["users"][user_id]["username"]
        db["users"][user_id]["photo_url"] = user_data.photo_url or db["users"][user_id]["photo_url"]
        db["users"][user_id]["role"] = assigned_role

    return db["users"][user_id]

# --- ЭНДПОИНТ 2: СЛУЖЕБНОЕ ИЗМЕНЕНИЕ БАЛАНСА И АДМИНКА ---
@app.post("/api/balance")
async def update_balance(data: BalanceUpdate):
    search_id = data.id if data.id else OWNER_ID
    
    if search_id not in db["users"]:
        db["users"][search_id] = {
            "id": search_id,
            "name": "Основатель (WOG)" if search_id == OWNER_ID else "Игрок казино",
            "username": "",
            "photo_url": "",
            "balance": 5000,
            "role": "admin" if search_id == OWNER_ID else "user"
        }

    db["users"][search_id]["balance"] += data.amount
    if db["users"][search_id]["balance"] < 0:
        db["users"][search_id]["balance"] = 0

    return {"success": True, "balance": db["users"][search_id]["balance"]}
# --- МОДЕЛИ ДАННЫХ ДЛЯ ИГР И ПРОМОКОДОВ ---
class DiceBet(BaseModel):
    id: int
    bet: int
    target: str  # На какой исход поставлено (under, seven, over, even, odd, c1-c6, sum2-sum12, p1-p6, anypair)

class PromoCreate(BaseModel):
    admin_id: int
    code: str
    reward: int
    uses: int

class PromoActivate(BaseModel):
    id: int
    code: str

# МАТРИЦА КОЭФФИЦИЕНТОВ КАЗИНО WOG НА PYTHON
MULTIPLIERS = {
    "under": 2.4, "seven": 5.9, "over": 2.4, "even": 2.0, "odd": 2.0,
    "c1": 3.2, "c2": 3.2, "c3": 3.2, "c4": 3.2, "c5": 3.2, "c6": 3.2,
    "sum2": 35.3, "sum3": 17.6, "sum4": 11.8, "sum5": 8.8, "sum6": 7.1, "sum7": 5.9, 
    "sum8": 7.1, "sum9": 8.8, "sum10": 11.8, "sum11": 17.6, "sum12": 35.3,
    "p1": 35.3, "p2": 35.3, "p3": 35.3, "p4": 35.3, "p5": 35.3, "p6": 35.3, "anypair": 5.9
}

# --- ЭНДПОИНТ 3: СЕРВЕРНЫЙ ДВИЖОК СТАВОК В КОСТИ ---
@app.post("/api/game/dice")
async def play_dice(bet_data: DiceBet):
    user_id = bet_data.id
    bet = bet_data.bet
    target = bet_data.target

    if user_id not in db["users"]:
        raise HTTPException(status_code=440, detail="User not found")
        
    player = db["users"][user_id]
    if player["balance"] < bet or bet <= 0:
        raise HTTPException(status_code=400, detail="Недостаточно монет для ставки!")

    if target not in MULTIPLIERS:
        raise HTTPException(status_code=400, detail="Неверный тип ставки")

    # Сервер честно генерирует бросок двух кубиков (от 1 до 6)
    val1 = random.randint(1, 6)
    val2 = random.randint(1, 6)
    dice_sum = val1 + val2
    is_pair = (val1 == val2)
    
    is_win = False

    # Логика проверки условий победы
    if target == "under" and dice_sum < 7: is_win = True
    elif target == "seven" and dice_sum == 7: is_win = True
    elif target == "over" and dice_sum > 7: is_win = True
    elif target == "even" and dice_sum % 2 == 0: is_win = True
    elif target == "odd" and dice_sum % 2 != 0: is_win = True
    elif target == "c1" and (val1 == 1 or val2 == 1): is_win = True
    elif target == "c2" and (val1 == 2 or val2 == 2): is_win = True
    elif target == "c3" and (val1 == 3 or val2 == 3): is_win = True
    elif target == "c4" and (val1 == 4 or val2 == 4): is_win = True
    elif target == "c5" and (val1 == 5 or val2 == 5): is_win = True
    elif target == "c6" and (val1 == 6 or val2 == 6): is_win = True
    elif target == f"sum{dice_sum}": is_win = True
    elif target == "anypair" and is_pair: is_win = True
    elif target == "p1" and is_pair and val1 == 1: is_win = True
    elif target == "p2" and is_pair and val1 == 2: is_win = True
    elif target == "p3" and is_pair and val1 == 3: is_win = True
    elif target == "p4" and is_pair and val1 == 4: is_win = True
    elif target == "p5" and is_pair and val1 == 5: is_win = True
    elif target == "p6" and is_pair and val1 == 6: is_win = True

    # Корректировка баланса игрока
    if is_win:
        win_amount = int(bet * MULTIPLIERS[target])
        profit = win_amount - bet
        player["balance"] += profit
    else:
        profit = -bet
        player["balance"] -= bet

    return {
        "success": True,
        "val1": val1,
        "val2": val2,
        "diceSum": dice_sum,
        "win": is_win,
        "winAmount": win_amount if is_win else 0,
        "balance": player["balance"]
    }

# --- ЭНДПОИНТ 4: СОЗДАНИЕ ПРОМОКОДА (АДМИН) ---
@app.post("/api/promo/create")
async def create_promo(data: PromoCreate):
    if data.admin_id != OWNER_ID:
        raise HTTPException(status_code=403, detail="Access denied")
        
    clean_code = data.code.strip().toUpperCase()
    db["promos"][clean_code] = {
        "reward": data.reward,
        "uses": data.uses,
        "claimed_by": []
    }
    return {"success": True}

# --- ЭНДПОИНТ 5: АКТИВАЦИЯ ПРОМОКОДА ---
@app.post("/api/promo/activate")
async def activate_promo(data: PromoActivate):
    user_id = data.id
    clean_code = data.code.strip().toUpperCase()

    if user_id not in db["users"]: raise HTTPException(status_code=404, detail="User not found")
    if clean_code not in db["promos"]: raise HTTPException(status_code=440, detail="Promo not found")
    
    promo = db["promos"][clean_code]
    if promo["uses"] <= 0: raise HTTPException(status_code=400, detail="Promo expired")
    if user_id in promo["claimed_by"]: raise HTTPException(status_code=400, detail="Already claimed")

    db["users"][user_id]["balance"] += promo["reward"]
    promo["uses"] -= 1
    promo["claimed_by"].append(user_id)

    return {"success": True, "balance": db["users"][user_id]["balance"], "message": f"Активирован код на +{promo['reward']} W!"}

# --- ЭНДПОИНТ 6: СПИСОК ПРОМОКОДОВ ---
@app.post("/api/promo/list")
async def list_promos(data: dict):
    if data.get("admin_id") != OWNER_ID: raise HTTPException(status_code=403, detail="Access denied")
    return db["promos"]

@app.get("/")
async def root():
    return {"status": "WOG Casino Core Python FastAPI Engine Active", "users_count": len(db["users"])}
