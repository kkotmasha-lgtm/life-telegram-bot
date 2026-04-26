import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")

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
        [KeyboardButton(text="📈 Аналитика финансов")]
    ],
    resize_keyboard=True
)

finance_analytics_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="📍 Сегодня", callback_data="finance_today")],
        [InlineKeyboardButton(text="📅 Неделя", callback_data="finance_week")],
        [InlineKeyboardButton(text="🗓 Месяц", callback_data="finance_month")]
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

def load_daily_messages():
    return load_json(DAILY_MESSAGES_FILE, {})

def save_daily_messages(data):
    save_json(DAILY_MESSAGES_FILE, data)

def load_finance():
    return load_json(FINANCE_FILE, [])

def save_finance(data):
    save_json(FINANCE_FILE, data)

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

def get_period_start(period):
    now = get_now().date()
    if period == "today":
        return now
    if period == "week":
        return now - timedelta(days=now.weekday())
    if period == "month":
        return now.replace(day=1)
    return now

def get_finance_period_stats(user_id, period):
    finance = load_finance()
    start_date = get_period_start(period)
    income_by_category = defaultdict(int)
    expense_by_category = defaultdict(int)
    total_income = 0
    total_expense = 0

    for item in finance:
        if item["user_id"] != user_id:
            continue
        item_date = datetime.strptime(item["date"], "%Y-%m-%d").date()
        if item_date < start_date:
            continue
        amount = item["amount"]
        category = item["category"]
        if amount > 0:
            total_income += amount
            income_by_category[category] += amount
        else:
            total_expense += amount
            expense_by_category[category] += amount

    return {
        "income": total_income,
        "expense": total_expense,
        "result": total_income + total_expense,
        "income_by_category": dict(income_by_category),
        "expense_by_category": dict(expense_by_category)
    }

def format_category_block(title, data, is_expense=False):
    if not data:
        return f"{title}\n— пока нет записей\n\n"
    text = f"{title}\n"
    sorted_items = sorted(data.items(), key=lambda item: abs(item[1]), reverse=True)
    for category, amount in sorted_items:
        text += f"• {category}: {amount if is_expense else '+'+str(amount)}\n"
    text += "\n"
    return text

def format_finance_period(user_id, period_name, period_key):
    stats = get_finance_period_stats(user_id, period_key)
    text = f"{period_name}\n\n"
    text += f"💚 Доходы: +{stats['income']}\n"
    text += f"💸 Расходы: {stats['expense']}\n"
    text += f"💰 Итог: {stats['result']}\n\n"
    text += format_category_block("💸 Расходы по категориям:", stats["expense_by_category"], True)
    text += format_category_block("💚 Доходы по категориям:", stats["income_by_category"])
    return text

async def reminder_loop():
    while True:
        tasks = load_tasks()
        for task in tasks:
            if task["status"] == "active" and task.get("date") == get_today() and task.get("time") == get_current_time() and not task.get("reminded"):
                await bot.send_message(task["user_id"], f"⏰ Напоминание!\n\n💫 {task['title']}")
                task["reminded"] = True
        save_tasks(tasks)
        await asyncio.sleep(30)

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Привет 💫 Я твой личный ассистент", reply_markup=main_keyboard)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    asyncio.create_task(reminder_loop())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
