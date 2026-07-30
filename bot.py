import asyncio
import logging
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Токен вашего бота из @BotFather
BOT_TOKEN = "8804973603:AAHqWkyFQv8qW2ZZUHn7RSqVddqVCN6_vXs"
# Ссылка на ваш сервер Render для функции Anti-Sleep
SERVER_URL = "https://onrender.com"
# Ссылка на ваше Mini App из BotFather (Direct Link)
MINI_APP_URL = "https://t.me"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- ФУНКЦИЯ ANTI-SLEEP (НЕ ДАЕТ СЕРВЕРУ ЗАСНУТЬ) ---
async def keep_server_alive():
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(SERVER_URL) as response:
                    if response.status == 200:
                        logging.info("Anti-Sleep: Сервер успешно спингован и бодрствует!")
                    else:
                        logging.warning(f"Anti-Sleep: Сервер вернул статус {response.status}")
        except Exception as e:
            logging.error(f"Anti-Sleep: Ошибка пинга сервера: {e}")
        
        # Ровно раз в 10 минут (600 секунд) будим сервер, предотвращая Sleep Mode на Render
        await asyncio.sleep(600)

# --- ОБРАБОТЧИК КОМАНДЫ /START ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    # Формируем красивую интерактивную кнопку запуска казино
    kb = InlineKeyboardBuilder()
    kb.button(
        text="🎰 Запустить WOG Casino",
        web_app=types.WebAppInfo(url="https://github.io")
    )
    
    welcome_text = (
        f"🌟 Добро пожаловать в игровой лаунчер **WOG Casino**, {message.from_user.first_name}!\n\n"
        f"У нас вы можете играть в захватывающие премиум-игры на виртуальные монеты **W-Coins**.\n"
        f"Ваш стартовый баланс уже ожидает вас внутри приложения.\n\n"
        f"Нажмите на кнопку ниже, чтобы начать игру прямо сейчас! 👇"
    )
    
    await message.answer(welcome_text, parse_mode="Markdown", reply_markup=kb.as_markup())

# --- ГЛАВНЫЙ ЗАПУСК БОТА ---
async def main():
    # Запускаем фоновую задачу фонового пинга сервера на Render
    asyncio.create_task(keep_server_alive())
    # Запускаем чтение сообщений бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
