import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict

import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

TASKS_FILE = "tasks.json"
FINANCE_FILE = "finance.json"
MEMORY_FILE = "memory.json"

TIMEZONE = ZoneInfo("Europe/Moscow")

bot = Bot(token=TOKEN)
dp = Dispatcher()

user_states = {}

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📅 Сегодня")],
        [KeyboardButton(text="➕ Добавить задачу")],
        [KeyboardButton(text="📋 Мои задачи")],
        [KeyboardButton(text="💰 Финансы")],
        [KeyboardButton(text="📊 Баланс")],
    ],
    resize_keyboard=True,
)

# ---------- UTILS ----------

def get_now():
    return datetime.now(TIMEZONE)

def get_today():
    return get_now().strftime("%Y-%m-%d")

def get_current_time():
    return get_now().strftime("%H:%M")

def load_json(filename, default):
    if not os.path.exists(filename):
        return default
    with open(filename, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ---------- MEMORY ----------

def load_memory():
    return load_json(MEMORY_FILE, {})

def save_memory(data):
    save_json(MEMORY_FILE, data)

def add_memory(user_id, role, text):
    memory = load_memory()
    uid = str(user_id)

    if uid not in memory:
        memory[uid] = []

    memory[uid].append({"role": role, "content": text})
    memory[uid] = memory[uid][-20:]

    save_memory(memory)

def get_memory(user_id):
    return load_memory().get(str(user_id), [])

# ---------- AI ----------

async def ask_ai(user_id, text):
    url = "https://openrouter.ai/api/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    messages = [
        {"role": "system", "content": "Ты простой, живой ассистент. Пиши коротко, без форматирования."}
    ]

    for m in get_memory(user_id):
        messages.append(m)

    messages.append({"role": "user", "content": text})

    data = {
        "model": "openrouter/free",
        "messages": messages,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data) as resp:
            result = await resp.json()

            if "choices" not in result:
                return "Ошибка AI"

            reply = result["choices"][0]["message"]["content"]

            add_memory(user_id, "user", text)
            add_memory(user_id, "assistant", reply)

            return reply

async def send_ai(message, text):
    await bot.send_chat_action(message.chat.id, "typing")
    reply = await ask_ai(message.from_user.id, text)
    await message.answer(reply)

# ---------- FINANCE ----------

def load_finance():
    return load_json(FINANCE_FILE, [])

def save_finance(data):
    save_json(FINANCE_FILE, data)

def parse_smart_finance(text):
    text = text.lower()

    amount_match = re.search(r"(\d+)", text)
    if not amount_match:
        return None

    amount = int(amount_match.group(1))

    if any(word in text for word in ["потрат", "расход", "купил", "купила"]):
        amount = -amount
    elif any(word in text for word in ["получ", "доход", "зп", "зарплат"]):
        amount = abs(amount)

    words = text.split()
    category = words[-1]

    return amount, category

# ---------- TASKS ----------

def load_tasks():
    return load_json(TASKS_FILE, [])

def save_tasks(data):
    save_json(TASKS_FILE, data)

def parse_smart_task(text):
    if "задач" not in text and "напомни" not in text:
        return None

    time_match = re.search(r"(\d{1,2}:\d{2})", text)
    time = time_match.group(1) if time_match else None

    return text, time

# ---------- HANDLER ----------

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Привет 💫", reply_markup=main_keyboard)

@dp.message()
async def handler(message: types.Message):
    text = message.text
    user_id = message.from_user.id

    # КНОПКИ
    if text == "📅 Сегодня":
        tasks = load_tasks()
        today = [t for t in tasks if t["user_id"] == user_id and t["date"] == get_today()]
        if not today:
            await message.answer("Нет задач")
        else:
            await message.answer("\n".join([t["title"] for t in today]))

    elif text == "📋 Мои задачи":
        tasks = load_tasks()
        user_tasks = [t for t in tasks if t["user_id"] == user_id]
        await message.answer("\n".join([t["title"] for t in user_tasks]) or "Пусто")

    elif text == "📊 Баланс":
        finance = load_finance()
        total = sum(x["amount"] for x in finance if x["user_id"] == user_id)
        await message.answer(f"Баланс: {total}")

    # УМНЫЕ ФИНАНСЫ
    finance_data = parse_smart_finance(text)
    if finance_data:
        amount, category = finance_data
        data = load_finance()

        data.append({
            "user_id": user_id,
            "amount": amount,
            "category": category,
            "date": get_today()
        })

        save_finance(data)

        return await message.answer(f"Записала: {amount} ({category})")

    # УМНЫЕ ЗАДАЧИ
    task_data = parse_smart_task(text)
    if task_data:
        title, time = task_data
        tasks = load_tasks()

        tasks.append({
            "user_id": user_id,
            "title": title,
            "date": get_today(),
            "time": time,
        })

        save_tasks(tasks)

        return await message.answer("Задача добавлена")

    # AI
    await send_ai(message, text)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
