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
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

TASKS_FILE = "tasks.json"
DAILY_MESSAGES_FILE = "daily_messages.json"
JOURNAL_FILE = "journal.json"
FINANCE_FILE = "finance.json"

TIMEZONE = ZoneInfo("Europe/Moscow")

MORNING_TIME = "08:00"
EVENING_TIME = "23:00"

bot = Bot(token=TOKEN)
dp = Dispatcher()

user_states = {}

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📅 Сегодня")],
        [KeyboardButton(text="➕ Добавить задачу")],
        [KeyboardButton(text="✅ Выполнить задачу")],
        [KeyboardButton(text="📋 Мои задачи")],
        [KeyboardButton(text="📓 Дневник")],
        [KeyboardButton(text="💰 Финансы")],
        [KeyboardButton(text="📊 Баланс")],
        [KeyboardButton(text="📈 Аналитика финансов")],
    ],
    resize_keyboard=True,
)

finance_analytics_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="📍 Сегодня", callback_data="finance_today")],
        [InlineKeyboardButton(text="📅 Неделя", callback_data="finance_week")],
        [InlineKeyboardButton(text="🗓 Месяц", callback_data="finance_month")],
    ]
)

def get_now():
    return datetime.now(TIMEZONE)

def get_today():
    return get_now().strftime("%Y-%m-%d")

def get_current_time():
    return get_now().strftime("%H:%M")

def load_json(filename, default):
    if not os.path.exists(filename):
        return default
    with open(filename, "r", encoding="utf-8") as file:
        return json.load(file)

def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

def extract_time(text):
    match = re.search(r"(\d{1,2}:\d{2})", text)
    if not match:
        return None
    hours, minutes = match.group(1).split(":")
    return f"{int(hours):02d}:{minutes}"

def load_tasks():
    tasks = load_json(TASKS_FILE, [])
    for task in tasks:
        task.setdefault("status", "active")
        task.setdefault("date", get_today())
        task.setdefault("reminded", False)
    save_json(TASKS_FILE, tasks)
    return tasks

def save_tasks(tasks):
    save_json(TASKS_FILE, tasks)

def load_journal():
    return load_json(JOURNAL_FILE, [])

def save_journal(journal):
    save_json(JOURNAL_FILE, journal)

def load_finance():
    return load_json(FINANCE_FILE, [])

def save_finance(finance):
    save_json(FINANCE_FILE, finance)

def get_today_tasks(user_id):
    tasks = load_tasks()
    return [
        task for task in tasks
        if task["user_id"] == user_id
        and task["date"] == get_today()
        and task["status"] == "active"
    ]

def parse_money(text):
    match = re.match(r"([+-]\d+)\s*(.*)", text)
    if not match:
        return None
    amount = int(match.group(1))
    category = match.group(2).strip() or "без категории"
    return amount, category

def calculate_balance(user_id):
    finance = load_finance()
    user_finance = [item for item in finance if item["user_id"] == user_id]

    balance = sum(item["amount"] for item in user_finance)
    today = get_today()

    today_income = sum(item["amount"] for item in user_finance if item["amount"] > 0 and item["date"] == today)
    today_expense = sum(item["amount"] for item in user_finance if item["amount"] < 0 and item["date"] == today)

    return balance, today_income, today_expense

# 🔥 ИСПРАВЛЕННЫЙ AI (НЕ ПАДАЕТ)
async def ask_ai(text):
    if not GROQ_API_KEY:
        return "❌ GROQ_API_KEY не найден"

    url = "https://api.groq.com/openai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    data = {
        "model": "llama3-70b-8192",
        "messages": [
            {"role": "system", "content": "Ты дружелюбный ассистент"},
            {"role": "user", "content": text},
        ],
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as response:
                result = await response.json()

                if "choices" not in result:
                    print("GROQ ERROR:", result)
                    return f"❌ Ошибка AI:\n{result}"

                return result["choices"][0]["message"]["content"]

    except Exception as e:
        print("AI EXCEPTION:", e)
        return "❌ Ошибка подключения к AI"

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Привет 💫 Я твой ассистент", reply_markup=main_keyboard)

@dp.message()
async def handler(message: types.Message):
    user_id = message.from_user.id
    text = message.text

    if text == "📅 Сегодня":
        tasks = get_today_tasks(user_id)
        if not tasks:
            await message.answer("Задач нет")
        else:
            await message.answer("\n".join([t["title"] for t in tasks]))

    elif text == "➕ Добавить задачу":
        user_states[user_id] = "task"
        await message.answer("Напиши задачу")

    elif user_states.get(user_id) == "task":
        tasks = load_tasks()
        tasks.append({
            "user_id": user_id,
            "title": text,
            "date": get_today(),
            "status": "active",
            "reminded": False,
        })
        save_tasks(tasks)
        user_states[user_id] = None
        await message.answer("Добавлено")

    elif text == "📓 Дневник":
        user_states[user_id] = "journal"
        await message.answer("Напиши запись")

    elif user_states.get(user_id) == "journal":
        journal = load_journal()
        journal.append({"user_id": user_id, "date": get_today(), "text": text})
        save_journal(journal)
        user_states[user_id] = None
        await message.answer("Сохранено")

    elif text == "💰 Финансы":
        user_states[user_id] = "money"
        await message.answer("Напиши +1000 или -500")

    elif user_states.get(user_id) == "money":
        parsed = parse_money(text)
        if not parsed:
            await message.answer("Ошибка формата")
            return
        amount, category = parsed
        finance = load_finance()
        finance.append({
            "user_id": user_id,
            "amount": amount,
            "category": category,
            "date": get_today(),
        })
        save_finance(finance)
        user_states[user_id] = None
        await message.answer("Записано")

    elif text == "📊 Баланс":
        balance, income, expense = calculate_balance(user_id)
        await message.answer(f"Баланс: {balance}")

    else:
        reply = await ask_ai(text)
        await message.answer(reply)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
