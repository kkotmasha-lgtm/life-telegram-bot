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
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

TASKS_FILE = "tasks.json"
FINANCE_FILE = "finance.json"
MEMORY_FILE = "memory.json"
USERS_FILE = "users.json"

TIMEZONE = ZoneInfo("Europe/Moscow")

bot = Bot(token=TOKEN)
dp = Dispatcher()

user_states = {}


def get_now():
    return datetime.now(TIMEZONE)


def get_today():
    return get_now().strftime("%Y-%m-%d")


def get_current_time():
    return get_now().strftime("%H:%M")


def load_json(filename, default):
    if not os.path.exists(filename):
        return default

    try:
        with open(filename, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return default


def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def load_tasks():
    data = load_json(TASKS_FILE, [])
    return data if isinstance(data, list) else []


def save_tasks(tasks):
    save_json(TASKS_FILE, tasks)


def load_finance():
    data = load_json(FINANCE_FILE, [])
    return data if isinstance(data, list) else []


def save_finance(finance):
    save_json(FINANCE_FILE, finance)


def load_memory():
    data = load_json(MEMORY_FILE, {})
    return data if isinstance(data, dict) else {}


def save_memory(memory):
    save_json(MEMORY_FILE, memory)


def load_users():
    data = load_json(USERS_FILE, {})
    return data if isinstance(data, dict) else {}


def save_users(users):
    save_json(USERS_FILE, users)


def get_user_name(user_id):
    users = load_users()
    return users.get(str(user_id), {}).get("name")


def save_user_name(user_id, name, message):
    users = load_users()
    users[str(user_id)] = {
        "name": name,
        "username": message.from_user.username,
        "first_name": message.from_user.first_name,
        "registered_at": get_now().strftime("%Y-%m-%d %H:%M"),
    }
    save_users(users)


def add_memory(user_id, role, text):
    memory = load_memory()
    user_key = str(user_id)

    if user_key not in memory:
        memory[user_key] = []

    memory[user_key].append({"role": role, "content": text})
    memory[user_key] = memory[user_key][-20:]
    save_memory(memory)


def get_memory(user_id):
    return load_memory().get(str(user_id), [])


def main_menu_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 Задачи", callback_data="tasks_menu"),
                InlineKeyboardButton(text="💰 Финансы", callback_data="finance_menu"),
            ],
            [
                InlineKeyboardButton(text="⏰ Напоминания", callback_data="reminders_menu"),
            ],
            [
                InlineKeyboardButton(text="🔄 Обновить меню", callback_data="main_menu"),
            ],
        ]
    )


def tasks_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить задачу", callback_data="add_task")],
            [InlineKeyboardButton(text="📋 Мои задачи", callback_data="show_tasks")],
            [InlineKeyboardButton(text="✅ Как отметить выполненной", callback_data="tasks_done_help")],
            [InlineKeyboardButton(text="❌ Как удалить задачу", callback_data="tasks_delete_help")],
            [InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")],
        ]
    )


def finance_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Записать доход/расход", callback_data="add_finance")],
            [InlineKeyboardButton(text="📊 Баланс", callback_data="show_balance")],
            [InlineKeyboardButton(text="📈 Аналитика", callback_data="show_finance_stats")],
            [InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")],
        ]
    )


def back_to_menu_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Меню", callback_data="main_menu")]
        ]
    )


def get_user_tasks(user_id):
    return [
        task for task in load_tasks()
        if isinstance(task, dict) and task.get("user_id") == user_id
    ]


def get_active_tasks(user_id):
    return [
        task for task in get_user_tasks(user_id)
        if task.get("status", "active") == "active"
    ]


def get_done_tasks(user_id):
    return [
        task for task in get_user_tasks(user_id)
        if task.get("status") == "done"
    ]


def format_main_menu_text(user_id):
    name = get_user_name(user_id) or "друг"

    active_tasks = get_active_tasks(user_id)
    done_tasks = get_done_tasks(user_id)

    balance, today_income, today_expense = calculate_balance(user_id)

    text = f"Привет, {name} 💫\n\n"
    text += "Вот твоё меню:\n\n"

    text += f"📋 Активные задачи: {len(active_tasks)}\n"

    if active_tasks:
        for index, task in enumerate(active_tasks[:5], start=1):
            task_date = task.get("date", "")
            task_time = task.get("time", "")
            when = f" — {task_date} {task_time}".strip()
            text += f"{index}. {task.get('title')}{when}\n"
    else:
        text += "Активных задач пока нет.\n"

    text += f"\n✅ Выполненные задачи: {len(done_tasks)}\n"
    text += f"\n💰 Баланс: {balance}\n"
    text += f"Сегодня доходы: +{today_income}\n"
    text += f"Сегодня расходы: {today_expense}\n\n"
    text += "Выбери, что хочешь сделать:"

    return text


async def send_main_menu(chat_id, user_id):
    await bot.send_message(
        chat_id,
        format_main_menu_text(user_id),
        reply_markup=main_menu_keyboard(),
    )


def extract_time(text):
    match = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
    if not match:
        return None

    hours = int(match.group(1))
    minutes = int(match.group(2))

    if hours > 23 or minutes > 59:
        return None

    return f"{hours:02d}:{minutes:02d}"


def extract_date(text):
    lower_text = text.lower()
    now = get_now()
    today = now.date()

    if "послезавтра" in lower_text:
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")

    if "завтра" in lower_text:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")

    if "через месяц" in lower_text:
        month = now.month + 1
        year = now.year

        if month > 12:
            month = 1
            year += 1

        day = min(now.day, 28)
        return datetime(year, month, day, tzinfo=TIMEZONE).strftime("%Y-%m-%d")

    match = re.search(r"через\s+(\d+)\s+д", lower_text)
    if match:
        return (today + timedelta(days=int(match.group(1)))).strftime("%Y-%m-%d")

    match = re.search(r"через\s+(\d+)\s+нед", lower_text)
    if match:
        return (today + timedelta(weeks=int(match.group(1)))).strftime("%Y-%m-%d")

    match = re.search(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b", text)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year_text = match.group(3)

        year = int(year_text) if year_text else now.year
        if year < 100:
            year += 2000

        try:
            date_obj = datetime(year, month, day, tzinfo=TIMEZONE).date()
            if not year_text and date_obj < today:
                date_obj = datetime(year + 1, month, day, tzinfo=TIMEZONE).date()
            return date_obj.strftime("%Y-%m-%d")
        except Exception:
            return get_today()

    return get_today()


def clean_task_text(text):
    task_text = text

    remove_patterns = [
        r"добавь задачу",
        r"запиши задачу",
        r"создай задачу",
        r"поставь задачу",
        r"напомни мне",
        r"напомни",
        r"напомнить",
        r"\bсегодня\b",
        r"\bзавтра\b",
        r"\bпослезавтра\b",
        r"через\s+\d+\s+д\w*",
        r"через\s+\d+\s+нед\w*",
        r"через\s+\d+\s+мес\w*",
        r"через\s+месяц",
        r"\b\d{1,2}\.\d{1,2}(?:\.\d{2,4})?\b",
        r"\bв\s*\d{1,2}:\d{2}\b",
        r"\d{1,2}:\d{2}",
    ]

    for pattern in remove_patterns:
        task_text = re.sub(pattern, "", task_text, flags=re.IGNORECASE)

    return task_text.strip()


def parse_smart_task(text):
    lower_text = text.lower()

    task_words = [
        "добавь задачу",
        "запиши задачу",
        "создай задачу",
        "поставь задачу",
        "напомни",
        "напомнить",
    ]

    if not any(word in lower_text for word in task_words):
        return None

    title = clean_task_text(text)
    task_date = extract_date(text)
    task_time = extract_time(text)

    if not title:
        return None

    return title, task_date, task_time


def add_task(user_id, title, task_date=None, task_time=None):
    tasks = load_tasks()

    task = {
        "user_id": user_id,
        "title": title,
        "date": task_date or get_today(),
        "status": "active",
        "reminded": False,
    }

    if task_time:
        task["time"] = task_time

    tasks.append(task)
    save_tasks(tasks)


def normalize_text(text):
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_task_number(text):
    match = re.search(r"\b(\d+)\s*(?:задач|задачу|задача|задачи)\b", text.lower())
    if match:
        return int(match.group(1))

    match = re.search(r"\b(?:задач|задачу|задача|задачи)\s*(\d+)\b", text.lower())
    if match:
        return int(match.group(1))

    return None


def clean_task_command_text(text):
    clean = text

    words = [
        "отмени", "отменить", "удали", "удалить", "убери", "убрать",
        "выполнила", "выполнил", "выполнено", "выполнена",
        "отметь", "закрой", "готово", "сделала", "сделал",
        "последнюю", "последняя", "последней",
    ]

    for word in words:
        clean = re.sub(word, "", clean, flags=re.IGNORECASE)

    clean = re.sub(r"последн\w*", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\b\d+\s*(задач|задачу|задача|задачи)\b", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\b(задач|задачу|задача|задачи)\s*\d+\b", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\bзадач[ауи]?\b", "", clean, flags=re.IGNORECASE)

    return clean.strip()


def detect_delete_task(text):
    text = text.lower()
    return (
        "задач" in text
        and any(word in text for word in ["удали", "удалить", "убери", "убрать", "отмени", "отменить"])
    )


def detect_complete_task(text):
    text = text.lower()
    return (
        "задач" in text
        and any(word in text for word in [
            "выполнила", "выполнил", "выполнено", "выполнена",
            "отметь", "готово", "сделала", "сделал", "закрой", "закрыть"
        ])
    )


def delete_task_by_text(user_id, text):
    tasks = load_tasks()
    user_tasks = []

    for index, task in enumerate(tasks):
        if isinstance(task, dict) and task.get("user_id") == user_id:
            user_tasks.append((index, task))

    if not user_tasks:
        return None

    if "последн" in text.lower():
        index, task = user_tasks[-1]
        deleted_task = tasks.pop(index)
        save_tasks(tasks)
        return deleted_task

    task_number = extract_task_number(text)

    if task_number and 1 <= task_number <= len(user_tasks):
        index, task = user_tasks[task_number - 1]
        deleted_task = tasks.pop(index)
        save_tasks(tasks)
        return deleted_task

    query = normalize_text(clean_task_command_text(text))

    if query:
        for index, task in user_tasks:
            title = normalize_text(task.get("title", ""))
            if query in title or title in query:
                deleted_task = tasks.pop(index)
                save_tasks(tasks)
                return deleted_task

    return None


def complete_task_by_text(user_id, text):
    tasks = load_tasks()
    active_tasks = []

    for index, task in enumerate(tasks):
        if (
            isinstance(task, dict)
            and task.get("user_id") == user_id
            and task.get("status", "active") == "active"
        ):
            active_tasks.append((index, task))

    if not active_tasks:
        return None

    if "последн" in text.lower():
        index, task = active_tasks[-1]
        tasks[index]["status"] = "done"
        tasks[index]["done_at"] = get_now().strftime("%Y-%m-%d %H:%M")
        save_tasks(tasks)
        return tasks[index]

    task_number = extract_task_number(text)

    if task_number and 1 <= task_number <= len(active_tasks):
        index, task = active_tasks[task_number - 1]
        tasks[index]["status"] = "done"
        tasks[index]["done_at"] = get_now().strftime("%Y-%m-%d %H:%M")
        save_tasks(tasks)
        return tasks[index]

    query = normalize_text(clean_task_command_text(text))

    if query:
        for index, task in active_tasks:
            title = normalize_text(task.get("title", ""))
            if query in title or title in query:
                tasks[index]["status"] = "done"
                tasks[index]["done_at"] = get_now().strftime("%Y-%m-%d %H:%M")
                save_tasks(tasks)
                return tasks[index]

    return None


def parse_smart_finance(text):
    original_text = text
    text = text.lower()

    finance_words = [
        "расход", "потрат", "купила", "купил",
        "доход", "получила", "получил", "зарплата", "зп",
        "запиши расход", "запиши доход",
    ]

    if not any(word in text for word in finance_words):
        return None

    amount_match = re.search(r"([+-]?\d+)", text)
    if not amount_match:
        return None

    amount = int(amount_match.group(1))

    income_words = ["доход", "получила", "получил", "зарплата", "зп"]
    expense_words = ["расход", "потрат", "купила", "купил"]

    if any(word in text for word in income_words):
        amount = abs(amount)
    elif any(word in text for word in expense_words):
        amount = -abs(amount)
    else:
        return None

    clean = original_text.lower()
    clean = re.sub(r"запиши", "", clean)
    clean = re.sub(
        r"доход|расход|получила|получил|потратила|потратил|купила|купил|зарплата|зп",
        "",
        clean,
    )
    clean = re.sub(r"[+-]?\d+", "", clean)
    clean = re.sub(r"\bр\b|\bруб\b|\bрублей\b|\bсегодня\b", "", clean)
    clean = clean.strip()

    category_words = clean.split()
    category = category_words[-1] if category_words else "без категории"

    return amount, category


def add_finance_operation(user_id, amount, category):
    finance = load_finance()

    finance.append({
        "user_id": user_id,
        "amount": amount,
        "category": category,
        "date": get_today(),
        "time": get_current_time(),
    })

    save_finance(finance)


def calculate_balance(user_id):
    finance = load_finance()
    user_finance = [item for item in finance if isinstance(item, dict) and item.get("user_id") == user_id]

    balance = sum(item.get("amount", 0) for item in user_finance)
    today = get_today()

    today_income = sum(
        item.get("amount", 0)
        for item in user_finance
        if item.get("amount", 0) > 0 and item.get("date") == today
    )

    today_expense = sum(
        item.get("amount", 0)
        for item in user_finance
        if item.get("amount", 0) < 0 and item.get("date") == today
    )

    return balance, today_income, today_expense


def detect_balance_question(text):
    text = text.lower()
    return any(word in text for word in [
        "баланс", "покажи баланс", "какой баланс",
        "остаток", "покажи остаток", "сколько денег",
    ])


def get_period_start(period):
    today = get_now().date()

    if period == "week":
        return today - timedelta(days=today.weekday())

    if period == "month":
        return today.replace(day=1)

    return today


def detect_finance_question(text):
    text = text.lower()

    question_words = [
        "какие расходы", "какие доходы", "покажи расходы",
        "покажи доходы", "финансы за", "расходы за",
        "доходы за", "сколько потратила", "сколько получил",
        "сколько получила", "операции сегодня", "операции за",
    ]

    if not any(word in text for word in question_words):
        return None

    if "месяц" in text:
        return "month"

    if "недел" in text:
        return "week"

    return "today"


def get_finance_stats(user_id, period):
    finance = load_finance()
    start_date = get_period_start(period)

    operations = []
    income = 0
    expense = 0
    income_by_category = defaultdict(int)
    expense_by_category = defaultdict(int)

    for item in finance:
        if not isinstance(item, dict) or item.get("user_id") != user_id:
            continue

        try:
            item_date = datetime.strptime(item.get("date"), "%Y-%m-%d").date()
        except Exception:
            continue

        if item_date < start_date:
            continue

        amount = item.get("amount", 0)
        category = item.get("category", "без категории")
        operations.append(item)

        if amount > 0:
            income += amount
            income_by_category[category] += amount
        else:
            expense += amount
            expense_by_category[category] += amount

    return {
        "income": income,
        "expense": expense,
        "result": income + expense,
        "operations": operations,
        "income_by_category": dict(income_by_category),
        "expense_by_category": dict(expense_by_category),
    }


def format_finance_stats(user_id, period):
    stats = get_finance_stats(user_id, period)

    period_names = {
        "today": "сегодня",
        "week": "за неделю",
        "month": "за месяц",
    }

    text = f"📊 Финансы {period_names.get(period, '')}\n\n"
    text += f"💚 Доходы: +{stats['income']}\n"
    text += f"💸 Расходы: {stats['expense']}\n"
    text += f"💰 Итог: {stats['result']}\n\n"

    if not stats["operations"]:
        text += "Операций пока нет."
        return text

    text += "Операции:\n"

    for item in stats["operations"]:
        amount = item.get("amount", 0)
        category = item.get("category", "без категории")
        time = item.get("time", "")

        sign = "+" if amount > 0 else ""
        text += f"• {time} {sign}{amount} — {category}\n"

    return text


async def ask_ai(user_id, text):
    if not OPENROUTER_API_KEY:
        return "OPENROUTER_API_KEY не найден в .env"

    url = "https://openrouter.ai/api/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    messages = [
        {
            "role": "system",
            "content": (
                "Ты встроенный AI ассистент внутри Telegram-бота пользователя. "
                "Ты помогаешь с задачами, финансами, дневником и поддержкой. "
                "Отвечай просто, коротко, по-человечески. "
                "Без markdown."
            ),
        }
    ]

    for item in get_memory(user_id):
        messages.append(item)

    messages.append({"role": "user", "content": text})

    data = {
        "model": "openrouter/free",
        "messages": messages,
        "temperature": 0.7,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as response:
                result = await response.json()

                if "choices" not in result:
                    print("OPENROUTER ERROR:", result)
                    return "Ошибка AI 😅"

                reply = result["choices"][0]["message"]["content"]

                add_memory(user_id, "user", text)
                add_memory(user_id, "assistant", reply)

                return reply

    except Exception as error:
        print("AI ERROR:", error)
        return "Ошибка подключения к AI 😅"


async def send_ai(message, text):
    await bot.send_chat_action(message.chat.id, "typing")
    reply = await ask_ai(message.from_user.id, text)
    await message.answer(reply)
    await send_main_menu(message.chat.id, message.from_user.id)


async def reminder_loop():
    while True:
        tasks = load_tasks()
        now = get_now()
        changed = False

        for task in tasks:
            if not isinstance(task, dict):
                continue

            if task.get("status", "active") != "active":
                continue

            if task.get("reminded"):
                continue

            task_time = task.get("time")
            if not task_time:
                continue

            try:
                task_datetime = datetime.strptime(
                    f"{task.get('date')} {task_time}",
                    "%Y-%m-%d %H:%M",
                ).replace(tzinfo=TIMEZONE)
            except Exception:
                continue

            if task_datetime <= now:
                await bot.send_message(
                    task["user_id"],
                    f"⏰ Напоминание!\n\n{task['title']}",
                )
                task["reminded"] = True
                changed = True

        if changed:
            save_tasks(tasks)

        await asyncio.sleep(30)


@dp.message(Command("start"))
async def start(message: types.Message):
    user_id = message.from_user.id

    if not get_user_name(user_id):
        user_states[user_id] = "name"
        await message.answer(
            "Привет 💫\n\nКак я могу к тебе обращаться?",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    await message.answer("Привет 💫")
    await send_main_menu(message.chat.id, user_id)


@dp.message(Command("menu"))
async def menu_command(message: types.Message):
    await send_main_menu(message.chat.id, message.from_user.id)


@dp.message(Command("help"))
async def help_command(message: types.Message):
    await message.answer(
        "Я умею вести задачи, финансы и напоминания.\n\n"
        "Примеры:\n"
        "напомни купить молоко завтра в 18:00\n"
        "запиши расход 300 кофе\n"
        "задача 1 выполнена\n"
        "удали задачу 2",
        reply_markup=back_to_menu_keyboard(),
    )


@dp.callback_query()
async def callbacks(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    data = callback.data

    await callback.answer()

    if data == "main_menu":
        await callback.message.answer(format_main_menu_text(user_id), reply_markup=main_menu_keyboard())
        return

    if data == "tasks_menu":
        await callback.message.answer(
            "📋 Задачи\n\nЧто хочешь сделать?",
            reply_markup=tasks_keyboard(),
        )
        return

    if data == "finance_menu":
        await callback.message.answer(
            "💰 Финансы\n\nЧто хочешь сделать?",
            reply_markup=finance_keyboard(),
        )
        return

    if data == "reminders_menu":
        await callback.message.answer(
            "⏰ Напоминания\n\n"
            "Примеры:\n"
            "напомни выпить воды в 21:00\n"
            "напомни позвонить завтра в 10:00\n"
            "напомни оплатить подписку 24.05 в 09:00\n"
            "напомни проверить через месяц в 12:00",
            reply_markup=back_to_menu_keyboard(),
        )
        return

    if data == "add_task":
        user_states[user_id] = "task"
        await callback.message.answer(
            "Напиши задачу.\n\nНапример:\nнапомни купить хлеб завтра в 18:00",
            reply_markup=back_to_menu_keyboard(),
        )
        return

    if data == "show_tasks":
        tasks = get_user_tasks(user_id)

        if not tasks:
            await callback.message.answer("У тебя пока нет задач.", reply_markup=back_to_menu_keyboard())
            return

        text = "📋 Мои задачи:\n\n"

        for index, task in enumerate(tasks, start=1):
            status = "✅" if task.get("status") == "done" else "🟡"
            date = task.get("date", "")
            time = task.get("time", "")
            when = f" ({date} {time})" if time else f" ({date})"
            text += f"{index}. {status} {task.get('title')}{when}\n"

        await callback.message.answer(text, reply_markup=back_to_menu_keyboard())
        return

    if data == "tasks_done_help":
        await callback.message.answer(
            "✅ Как отметить задачу выполненной:\n\n"
            "задача 1 выполнена\n"
            "отметь последнюю задачу\n"
            "задача купить молоко выполнена",
            reply_markup=back_to_menu_keyboard(),
        )
        return

    if data == "tasks_delete_help":
        await callback.message.answer(
            "❌ Как удалить задачу:\n\n"
            "удали задачу 1\n"
            "отмени последнюю задачу\n"
            "удали задачу купить молоко",
            reply_markup=back_to_menu_keyboard(),
        )
        return

    if data == "add_finance":
        user_states[user_id] = "money"
        await callback.message.answer(
            "Напиши доход или расход.\n\nНапример:\n-500 кофе\n+1000 зарплата\nпотратила 300 еда",
            reply_markup=back_to_menu_keyboard(),
        )
        return

    if data == "show_balance":
        balance, income, expense = calculate_balance(user_id)
        await callback.message.answer(
            f"📊 Баланс: {balance}\n\n"
            f"Сегодня:\n"
            f"💚 Доходы: +{income}\n"
            f"💸 Расходы: {expense}",
            reply_markup=back_to_menu_keyboard(),
        )
        return

    if data == "show_finance_stats":
        await callback.message.answer(
            format_finance_stats(user_id, "today"),
            reply_markup=back_to_menu_keyboard(),
        )
        return


@dp.message()
async def handler(message: types.Message):
    user_id = message.from_user.id
    text = message.text

    if not text:
        await message.answer("Я пока умею работать только с текстом 🙂")
        return

    if user_states.get(user_id) == "name":
        name = text.strip()
        save_user_name(user_id, name, message)
        user_states[user_id] = None

        await message.answer(f"Приятно познакомиться, {name} 💫")
        await send_main_menu(message.chat.id, user_id)
        return

    if user_states.get(user_id) == "task":
        task_time = extract_time(text)
        task_date = extract_date(text)
        title = clean_task_text(text)

        if not title:
            title = text.strip()

        add_task(user_id, title, task_date, task_time)
        user_states[user_id] = None

        if task_time:
            await message.answer(f"Добавила задачу: {title}\nНапомню {task_date} в {task_time}")
        else:
            await message.answer(f"Добавила задачу: {title}")

        await send_main_menu(message.chat.id, user_id)
        return

    if user_states.get(user_id) == "money":
        parsed = parse_smart_finance(text)

        if not parsed:
            simple_match = re.match(r"([+-]\d+)\s*(.*)", text)

            if not simple_match:
                await message.answer("Не поняла формат. Попробуй так: -500 кофе или +1000 зарплата")
                return

            amount = int(simple_match.group(1))
            category = simple_match.group(2).strip() or "без категории"
        else:
            amount, category = parsed

        add_finance_operation(user_id, amount, category)
        user_states[user_id] = None

        await message.answer(f"Записала: {amount} ({category})")
        await send_main_menu(message.chat.id, user_id)
        return

    if text.lower() in ["меню", "мои данные", "главное меню"]:
        await send_main_menu(message.chat.id, user_id)
        return

    if detect_delete_task(text):
        deleted_task = delete_task_by_text(user_id, text)

        if deleted_task:
            await message.answer(f"Убрала задачу: {deleted_task['title']}")
        else:
            await message.answer("Не нашла такую задачу.")

        await send_main_menu(message.chat.id, user_id)
        return

    if detect_complete_task(text):
        completed_task = complete_task_by_text(user_id, text)

        if completed_task:
            await message.answer(f"Отметила выполненной: {completed_task['title']}")
        else:
            await message.answer("Не нашла такую активную задачу.")

        await send_main_menu(message.chat.id, user_id)
        return

    if detect_balance_question(text):
        balance, income, expense = calculate_balance(user_id)
        await message.answer(
            f"📊 Баланс: {balance}\n\n"
            f"Сегодня:\n"
            f"💚 Доходы: +{income}\n"
            f"💸 Расходы: {expense}"
        )
        await send_main_menu(message.chat.id, user_id)
        return

    finance_period = detect_finance_question(text)

    if finance_period:
        await message.answer(format_finance_stats(user_id, finance_period))
        await send_main_menu(message.chat.id, user_id)
        return

    task_data = parse_smart_task(text)

    if task_data:
        title, task_date, task_time = task_data
        add_task(user_id, title, task_date, task_time)

        if task_time:
            await message.answer(f"Добавила задачу: {title}\nНапомню {task_date} в {task_time}")
        else:
            await message.answer(f"Добавила задачу: {title}")

        await send_main_menu(message.chat.id, user_id)
        return

    finance_data = parse_smart_finance(text)

    if finance_data:
        amount, category = finance_data
        add_finance_operation(user_id, amount, category)
        await message.answer(f"Записала: {amount} ({category})")
        await send_main_menu(message.chat.id, user_id)
        return

    await send_ai(message, text)


async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    asyncio.create_task(reminder_loop())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
