import os
import random
import logging
import asyncio  # ПРИНУДИТЕЛЬНО ИМПОРТИРОВАЛИ МОДУЛЬ (ОШИБКА ИСПРАВЛЕНА!)
from typing import Optional, Dict
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder

logging.basicConfig(level=logging.INFO)

# КОНФИГУРАЦИЯ И ТОКЕНЫ
BOT_TOKEN = "8804973603:AAHqWkyFQv8qW2ZZUHn7RSqVddqVCN6_vXs"
OWNER_ID = 6682822292
RENDER_URL = "https://onrender.com"  # URL вашего бэкенда

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Глобальная база данных игроков и промокодов в оперативной памяти Python
db: Dict[str, dict] = {
    "users": {},
    "promos": {}
}

# --- НАСТРОЙКА ЖИЗНЕННОГО ЦИКЛА (LIFESPAN) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # При старте сервера FastAPI автоматически регистрирует вебхук в Telegram
    webhook_url = f"{RENDER_URL}/tg-webhook"
    logging.info(f"Казино-движок: Установка вебхука на {webhook_url}")
    await bot.set_webhook(url=webhook_url, drop_pending_updates=True)
    yield
    # При выключении сервера удаляем вебхук
    logging.info("Казино-движок: Удаление вебхука Telegram...")
    await bot.delete_webhook()

# Инициализируем FastAPI с привязкой умного вебхука
app = FastAPI(title="WOG Casino Python Engine", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ПРИЕМ УВЕДОМЛЕНИЙ ОТ ТЕЛЕГРАМА (ВЕБХУК-ЭНДПОИНТ)
@app.post("/tg-webhook")
async def telegram_webhook(request: Request):
    try:
        update_data = await request.json()
        update = types.Update(**update_data)
        await dp.feed_update(bot, update)
        return {"status": "ok"}
    except Exception as e:
        logging.error(f"Ошибка обработки вебхука: {e}")
        return {"status": "error"}

# --- СТРУКТУРЫ ДАННЫХ (МОДЕЛИ) ---
class UserLogin(BaseModel):
    id: int
    first_name: Optional[str] = "Игрок"
    username: Optional[str] = ""
    photo_url: Optional[str] = ""
    auth_data: Optional[str] = ""

class BalanceUpdate(BaseModel):
    id: int
    amount: int
# --- АВТОРИЗАЦИЯ И РЕГИСТРАЦИЯ ИГРОКА НА СЕРВЕРЕ ---
@app.post("/api/user")
async def login_user(user_data: UserLogin):
    user_id = user_data.id
    
    if not user_id or user_id == OWNER_ID:
        user_id = OWNER_ID
        user_data.first_name = "Основатель (WOG)"
        user_data.username = "FounderAdmin"

    assigned_role = "admin" if user_id == OWNER_ID else "user"

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
        db["users"][user_id]["name"] = user_data.first_name or db["users"][user_id]["name"]
        db["users"][user_id]["username"] = user_data.username or db["users"][user_id]["username"]
        db["users"][user_id]["photo_url"] = user_data.photo_url or db["users"][user_id]["photo_url"]
        db["users"][user_id]["role"] = assigned_role

    return db["users"][user_id]

# --- ИЗМЕНЕНИЕ И НАЧИСЛЕНИЕ ИГРОВОГО БАЛАНСА ---
@app.post("/api/balance")
async def update_balance(data: BalanceUpdate):
    search_id = data.id if data.id else OWNER_ID
    
    if search_id not in db["users"]:
        db["users"][search_id] = {
            "id": search_id,
            "name": "Основатель (WOG)" if search_id == OWNER_ID else "Игрок",
            "username": "",
            "photo_url": "",
            "balance": 5000,
            "role": "admin" if search_id == OWNER_ID else "user"
        }

    db["users"][search_id]["balance"] += data.amount
    if db["users"][search_id]["balance"] < 0:
        db["users"][search_id]["balance"] = 0

    return {"success": True, "balance": db["users"][search_id]["balance"]}

# --- СТРУКТУРЫ ДАННЫХ И КОЭФФИЦИЕНТЫ ДЛЯ КОСТЕЙ ---
class DiceBet(BaseModel):
    id: int
    bet: int
    target: str

MULTIPLIERS = {
    "under": 2.4, "seven": 5.9, "over": 2.4, "even": 2.0, "odd": 2.0,
    "c1": 3.2, "c2": 3.2, "c3": 3.2, "c4": 3.2, "c5": 3.2, "c6": 3.2,
    "sum2": 35.3, "sum3": 17.6, "sum4": 11.8, "sum5": 8.8, "sum6": 7.1, "sum7": 5.9, 
    "sum8": 7.1, "sum9": 8.8, "sum10": 11.8, "sum11": 17.6, "sum12": 35.3,
    "p1": 35.3, "p2": 35.3, "p3": 35.3, "p4": 35.3, "p5": 35.3, "p6": 35.3, "anypair": 5.9
}

# --- ДВИЖОК СТАВОК В КОСТИ ---
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

    val1 = random.randint(1, 6)
    val2 = random.randint(1, 6)
    dice_sum = val1 + val2
    is_pair = (val1 == val2)
    
    is_win = False

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

    if is_win:
        win_amount = int(bet * MULTIPLIERS[target])
        profit = win_amount - bet
        player["balance"] += profit
    else:
        player["balance"] -= bet

    return {
        "success": True,
        "val1": val1,
        "val2": val2,
        "diceSum": dice_sum,
        "win": is_win,
        "balance": player["balance"]
    }
# --- СТРУКТУРЫ ДАННЫХ ДЛЯ ПРОМОКОДОВ ---
class PromoCreate(BaseModel):
    admin_id: int
    code: str
    reward: int
    uses: int

class PromoActivate(BaseModel):
    id: int
    code: str

# --- ЭНДПОИНТЫ ПРОМОКОДОВ ---
@app.post("/api/promo/create")
async def create_promo(data: PromoCreate):
    if data.admin_id != OWNER_ID:
        raise HTTPException(status_code=403, detail="Access denied")
        
    clean_code = data.code.strip().upper()
    db["promos"][clean_code] = {
        "reward": data.reward,
        "uses": data.uses,
        "claimed_by": []
    }
    return {"success": True}

@app.post("/api/promo/activate")
async def activate_promo(data: PromoActivate):
    user_id = data.id
    clean_code = data.code.strip().upper()

    if user_id not in db["users"]: raise HTTPException(status_code=440, detail="User not found")
    if clean_code not in db["promos"]: raise HTTPException(status_code=440, detail="Promo not found")
    
    promo = db["promos"][clean_code]
    if promo["uses"] <= 0: raise HTTPException(status_code=400, detail="Promo expired")
    if user_id in promo["claimed_by"]: raise HTTPException(status_code=400, detail="Already claimed")

    db["users"][user_id]["balance"] += promo["reward"]
    promo["uses"] -= 1
    promo["claimed_by"].append(user_id)

    return {"success": True, "balance": db["users"][user_id]["balance"], "message": f"Активирован код на +{promo['reward']} W!"}

@app.post("/api/promo/list")
async def list_promos(data: dict):
    if data.get("admin_id") != OWNER_ID: raise HTTPException(status_code=403, detail="Access denied")
    return db["promos"]


# =====================================================================
# --- ЛОГИКА TELEGRAM-БОТА (ОБРАБОТКА ВНУТРИ ВЕБХУКА FASTAPI) ---
# =====================================================================

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    # Создаем красивую кнопку запуска приложения Mini App прямо в чате
    kb = InlineKeyboardBuilder()
    kb.button(
        text="🎰 Играть в WOG Casino",
        web_app=types.WebAppInfo(url="https://github.io")
    )
    
    welcome_text = (
        f"🌟 **Добро пожаловать в WOG Casino**, {message.from_user.first_name}!\n\n"
        f"У нас вы можете играть в премиальные игры на виртуальные монеты **W-Coins**.\n"
        f"Ваш стартовый баланс в размере 5000 W уже зачислен в кошелёк.\n\n"
        f"Нажмите на кнопку ниже, чтобы открыть игровой хаб! 👇"
    )
    
    await message.answer(welcome_text, parse_mode="Markdown", reply_markup=kb.as_markup())
