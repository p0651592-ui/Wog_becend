from __future__ import annotations

import asyncio
import logging
import os

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="💎 Баланс")],
        [KeyboardButton(text="🏆 Рейтинг")],
    ],
    resize_keyboard=True,
    selective=True,
)


async def fetch_profile(telegram_id: int) -> dict:
    url = f"{BACKEND_URL.rstrip('/')}/api/profile/{telegram_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=15) as response:
            response.raise_for_status()
            return await response.json()


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Добро пожаловать в WOG.\n\nНажми кнопку «👤 Профиль» или используй /bal / /бал.",
        reply_markup=MENU,
    )


@dp.message(F.text.in_({"👤 Профиль", "/bal", "/бал", "/profile", "💎 Баланс"}))
async def show_profile(message: Message) -> None:
    try:
        profile = await fetch_profile(message.from_user.id)
        await message.answer(profile.get("text") or "Профиль недоступен.", reply_markup=MENU)
    except Exception as exc:  # pragma: no cover - bot runtime errors only
        logging.exception("Failed to load profile: %s", exc)
        await message.answer("Не удалось загрузить профиль. Попробуй ещё раз позже.", reply_markup=MENU)


@dp.message(Command("top"))
async def show_rating(message: Message) -> None:
    await message.answer("Рейтинг игроков будет подключён следующим этапом.", reply_markup=MENU)


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
