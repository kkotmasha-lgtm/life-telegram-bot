import asyncio
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

bot = Bot(token=TOKEN)
dp = Dispatcher()

TIMEZONE = ZoneInfo("Europe/Moscow")

TASKS_FILE = "tasks.json"


def load_tasks():
    if not os.path.exists(TASKS_FILE):
        return []
    with open(TASKS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_tasks(tasks):
    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)


main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📅 Сегодня")],
        [KeyboardButton(text="➕ Добавить задачу")],
        [KeyboardButton(text="🤖 Поговорить с ассистентом")]
    ],
    resize_keyboard=True
)


async def ask_ai(text):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "llama3-70b-8192",
        "messages": [
            {"role": "system", "content": "Ты заботливый и умный ассистент. Помогаешь планировать день, поддерживаешь и даёшь советы."},
            {"role": "user", "content": text}
        ]
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data) as resp:
            result = await resp.json()
            return result["choices"][0]["message"]["content"]


@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Привет 💫 Я твой умный ассистент", reply_markup=main_keyboard)


@dp.message()
async def handler(message: types.Message):
    text = message.text

    if text == "📅 Сегодня":
        tasks = load_tasks()
        if not tasks:
            await message.answer("Сегодня задач нет ✨")
        else:
            response = "\n".join(f"• {t}" for t in tasks)
            await message.answer(response)

    elif text == "➕ Добавить задачу":
        await message.answer("Напиши задачу")

    elif text.startswith("➕") or len(text) > 2:
        tasks = load_tasks()
        tasks.append(text)
        save_tasks(tasks)
        await message.answer("Добавила ✨")

    else:
        reply = await ask_ai(text)
        await message.answer(reply)


async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
