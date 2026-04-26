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
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

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


def load_daily_messages():
    return load_json(DAILY_MESSAGES_FILE, {})


def save_daily_messages(data):
    save_json(DAILY_MESSAGES_FILE, data)


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

    today_income = sum(
        item["amount"]
        for item in user_finance
        if item["amount"] > 0 and item["date"] == today
    )

    today_expense = sum(
        item["amount"]
        for item in user_finance
        if item["amount"] < 0 and item["date"] == today
    )

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
        "expense_by_category": dict(expense_by_category),
    }


def format_category_block(title, data, is_expense=False):
    if not data:
        return f"{title}\n— пока нет записей\n\n"

    text = f"{title}\n"

    sorted_items = sorted(
        data.items(),
        key=lambda item: abs(item[1]),
        reverse=True,
    )

    for category, amount in sorted_items:
        if is_expense:
            text += f"• {category}: {amount}\n"
        else:
            text += f"• {category}: +{amount}\n"

    text += "\n"
    return text


def format_finance_period(user_id, period_name, period_key):
    stats = get_finance_period_stats(user_id, period_key)

    text = f"{period_name}\n\n"
    text += f"💚 Доходы: +{stats['income']}\n"
    text += f"💸 Расходы: {stats['expense']}\n"
    text += f"💰 Итог: {stats['result']}\n\n"

    text += format_category_block(
        "💸 Расходы по категориям:",
        stats["expense_by_category"],
        is_expense=True,
    )

    text += format_category_block(
        "💚 Доходы по категориям:",
        stats["income_by_category"],
        is_expense=False,
    )

    return text


def get_known_user_ids():
    user_ids = set()

    for task in load_tasks():
        user_ids.add(task["user_id"])

    for entry in load_journal():
        user_ids.add(entry["user_id"])

    for item in load_finance():
        user_ids.add(item["user_id"])

    return list(user_ids)


async def ask_ai(text):
    if not OPENROUTER_API_KEY:
        return "❌ OPENROUTER_API_KEY не найден в .env"

    url = "https://openrouter.ai/api/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com",
        "X-OpenRouter-Title": "Life Telegram Bot",
    }

    data = {
        "model": "meta-llama/llama-3.1-8b-instruct:free",
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты мягкий, заботливый и умный личный ассистент. "
                    "Помогаешь с планированием, задачами, дневником, финансами и поддержкой. "
                    "Не дави, не критикуй, говори тепло, по делу и по-человечески. "
                    "Пиши на русском."
                ),
            },
            {
                "role": "user",
                "content": text,
            },
        ],
        "temperature": 0.7,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as response:
                result = await response.json()

                if "choices" not in result:
                    print("OPENROUTER ERROR:", result)
                    return f"❌ Ошибка AI:\n{result}"

                return result["choices"][0]["message"]["content"]

    except Exception as error:
        print("AI ошибка:", error)
        return "❌ У меня сейчас не получилось ответить как AI. Попробуй ещё раз."


async def reminder_loop():
    while True:
        tasks = load_tasks()

        for task in tasks:
            if (
                task["status"] == "active"
                and task.get("date") == get_today()
                and task.get("time") == get_current_time()
                and not task.get("reminded")
            ):
                await bot.send_message(
                    task["user_id"],
                    f"⏰ Напоминание!\n\n💫 {task['title']}\n\nТы справишься ✨",
                )
                task["reminded"] = True

        save_tasks(tasks)
        await asyncio.sleep(30)


async def daily_messages_loop():
    while True:
        now = get_current_time()
        today = get_today()
        daily_data = load_daily_messages()
        user_ids = get_known_user_ids()

        for user_id in user_ids:
            user_key = str(user_id)

            if user_key not in daily_data:
                daily_data[user_key] = {}

            if now == MORNING_TIME and daily_data[user_key].get("morning") != today:
                await bot.send_message(
                    user_id,
                    "🌅 Доброе утро 💫\n\nСверим планы на сегодня?\nНужно что-то добавить? ✨",
                )
                daily_data[user_key]["morning"] = today

            if now == EVENING_TIME and daily_data[user_key].get("evening") != today:
                await bot.send_message(
                    user_id,
                    "🌙 Как прошёл твой день? 💭\n\nУже есть планы на завтра?\nХочу записать ✨",
                )
                daily_data[user_key]["evening"] = today

        save_daily_messages(daily_data)
        await asyncio.sleep(30)


@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "Привет 💫 Я твой умный ассистент\n\nДавай сделаем твой день чуть лучше ✨",
        reply_markup=main_keyboard,
    )


@dp.callback_query()
async def callback_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    data = callback.data

    if data == "finance_today":
        response = format_finance_period(user_id, "📍 Сегодня", "today")
        await callback.message.edit_text(response, reply_markup=finance_analytics_keyboard)

    elif data == "finance_week":
        response = format_finance_period(user_id, "📅 Эта неделя", "week")
        await callback.message.edit_text(response, reply_markup=finance_analytics_keyboard)

    elif data == "finance_month":
        response = format_finance_period(user_id, "🗓 Этот месяц", "month")
        await callback.message.edit_text(response, reply_markup=finance_analytics_keyboard)

    await callback.answer()


@dp.message()
async def handler(message: types.Message):
    user_id = message.from_user.id
    text = message.text

    if not text:
        await message.answer("Я пока умею работать только с текстом 🙂")
        return

    if text == "📅 Сегодня":
        tasks = get_today_tasks(user_id)

        if not tasks:
            await message.answer("🌿 На сегодня задач пока нет\n\nМожет добавим что-нибудь приятное? ✨")
        else:
            response = "✨ Твои задачи на сегодня:\n\n"

            for index, task in enumerate(tasks, start=1):
                time = f" ({task['time']})" if "time" in task else ""
                response += f"{index}. 💫 {task['title']}{time}\n"

            await message.answer(response)

    elif text == "➕ Добавить задачу":
        user_states[user_id] = "task"
        await message.answer("✨ Напиши задачу\n\nНапример:\nспорт в 19:00 💪")

    elif user_states.get(user_id) == "task":
        tasks = load_tasks()
        task_time = extract_time(text)

        task = {
            "user_id": user_id,
            "title": text,
            "date": get_today(),
            "status": "active",
            "reminded": False,
        }

        if task_time:
            task["time"] = task_time

        tasks.append(task)
        save_tasks(tasks)

        user_states[user_id] = None

        if task_time:
            await message.answer(f"💫 Добавила задачу\n\n{text}\n\n⏰ Напомню в {task_time}")
        else:
            await message.answer(f"💫 Добавила задачу\n\n{text}")

    elif text == "✅ Выполнить задачу":
        tasks = get_today_tasks(user_id)

        if not tasks:
            await message.answer("🌿 Пока нечего отмечать\n\nНо это тоже ок ✨")
            return

        user_states[user_id] = "done"

        response = "💫 Какую задачу отметим выполненной?\n\n"

        for index, task in enumerate(tasks, start=1):
            response += f"{index}. {task['title']}\n"

        response += "\nНапиши номер ✨"

        await message.answer(response)

    elif user_states.get(user_id) == "done":
        if not text.isdigit():
            await message.answer("Напиши номер задачи ✨")
            return

        today_tasks = get_today_tasks(user_id)
        task_number = int(text)

        if task_number < 1 or task_number > len(today_tasks):
            await message.answer("Такой задачи нет 🙈")
            return

        selected_task = today_tasks[task_number - 1]
        tasks = load_tasks()

        for task in tasks:
            if (
                task["user_id"] == selected_task["user_id"]
                and task["title"] == selected_task["title"]
                and task["date"] == selected_task["date"]
            ):
                task["status"] = "done"
                break

        save_tasks(tasks)
        user_states[user_id] = None

        await message.answer(f"🎉 Готово!\n\n{selected_task['title']}")

    elif text == "📋 Мои задачи":
        tasks = load_tasks()
        user_tasks = [task for task in tasks if task["user_id"] == user_id]

        if not user_tasks:
            await message.answer("🌿 У тебя пока нет задач\n\nДавай начнём ✨")
        else:
            response = "📋 Все задачи:\n\n"

            for task in user_tasks:
                status = "✅" if task["status"] == "done" else "🟡"
                time = f" ({task['time']})" if "time" in task else ""
                response += f"{status} {task['title']}{time}\n"

            await message.answer(response)

    elif text == "📓 Дневник":
        user_states[user_id] = "journal"
        await message.answer("💭 Как прошёл день?\n\nМожешь написать всё, что чувствуешь ✨")

    elif user_states.get(user_id) == "journal":
        journal = load_journal()

        journal.append({
            "user_id": user_id,
            "date": get_today(),
            "time": get_current_time(),
            "text": text,
        })

        save_journal(journal)
        user_states[user_id] = None

        ai_reply = await ask_ai(
            f"Я записала в дневник: {text}. "
            f"Дай короткий, мягкий поддерживающий отклик."
        )

        await message.answer(f"📓 Записала\n\n{ai_reply}")

    elif text == "💰 Финансы":
        user_states[user_id] = "money"
        await message.answer("💸 Добавь расход или доход\n\nНапример:\n-500 еда 🍜\n+30000 зарплата ✨")

    elif user_states.get(user_id) == "money":
        parsed = parse_money(text)

        if not parsed:
            await message.answer("Не поняла формат 😅\n\nПопробуй так:\n-500 еда\n+30000 зарплата")
            return

        amount, category = parsed
        finance = load_finance()

        finance.append({
            "user_id": user_id,
            "amount": amount,
            "category": category,
            "date": get_today(),
            "time": get_current_time(),
        })

        save_finance(finance)
        user_states[user_id] = None

        if amount > 0:
            await message.answer(f"💚 Доход записан: +{amount}\n\nКатегория: {category}")
        else:
            await message.answer(f"💸 Расход записан: {amount}\n\nКатегория: {category}")

    elif text == "📊 Баланс":
        balance, income, expense = calculate_balance(user_id)

        await message.answer(
            f"💰 Баланс: {balance}\n\n"
            f"Сегодня:\n"
            f"💚 Доход: +{income}\n"
            f"💸 Расход: {expense}"
        )

    elif text == "📈 Аналитика финансов":
        await message.answer(
            "📈 За какой период показать аналитику?",
            reply_markup=finance_analytics_keyboard,
        )

    else:
        reply = await ask_ai(text)
        await message.answer(reply)


async def main():
    await bot.delete_webhook(drop_pending_updates=True)

    asyncio.create_task(reminder_loop())
    asyncio.create_task(daily_messages_loop())

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
