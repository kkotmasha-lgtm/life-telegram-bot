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
        [KeyboardButton(text="📈 Аналитика финансов")],
    ],
    resize_keyboard=True,
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
    if not isinstance(data, list):
        return []
    return [task for task in data if isinstance(task, dict)]


def save_tasks(tasks):
    save_json(TASKS_FILE, tasks)


def load_finance():
    data = load_json(FINANCE_FILE, [])
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def save_finance(finance):
    save_json(FINANCE_FILE, finance)


def load_memory():
    data = load_json(MEMORY_FILE, {})
    if not isinstance(data, dict):
        return {}
    return data


def save_memory(memory):
    save_json(MEMORY_FILE, memory)


def add_memory(user_id, role, text):
    memory = load_memory()
    user_key = str(user_id)

    if user_key not in memory:
        memory[user_key] = []

    memory[user_key].append({
        "role": role,
        "content": text,
    })

    memory[user_key] = memory[user_key][-20:]
    save_memory(memory)


def get_memory(user_id):
    return load_memory().get(str(user_id), [])


def extract_time(text):
    match = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
    if not match:
        return None

    hours = int(match.group(1))
    minutes = int(match.group(2))

    if hours < 0 or hours > 23 or minutes < 0 or minutes > 59:
        return None

    return f"{hours:02d}:{minutes:02d}"


def extract_date(text):
    lower_text = text.lower()
    now = get_now()
    today = now.date()

    if "завтра" in lower_text:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")

    if "послезавтра" in lower_text:
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")

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
        days = int(match.group(1))
        return (today + timedelta(days=days)).strftime("%Y-%m-%d")

    match = re.search(r"через\s+(\d+)\s+нед", lower_text)
    if match:
        weeks = int(match.group(1))
        return (today + timedelta(weeks=weeks)).strftime("%Y-%m-%d")

    match = re.search(r"через\s+(\d+)\s+мес", lower_text)
    if match:
        months = int(match.group(1))
        month = now.month + months
        year = now.year

        while month > 12:
            month -= 12
            year += 1

        day = min(now.day, 28)
        return datetime(year, month, day, tzinfo=TIMEZONE).strftime("%Y-%m-%d")

    match = re.search(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b", text)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year_text = match.group(3)

        if year_text:
            year = int(year_text)
            if year < 100:
                year += 2000
        else:
            year = now.year

        try:
            date_obj = datetime(year, month, day, tzinfo=TIMEZONE).date()

            if not year_text and date_obj < today:
                date_obj = datetime(year + 1, month, day, tzinfo=TIMEZONE).date()

            return date_obj.strftime("%Y-%m-%d")
        except Exception:
            return get_today()

    return get_today()


def normalize_text(text):
    text = text.lower()
    text = text.replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


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

    task_time = extract_time(text)
    task_date = extract_date(text)

    task_text = text

    task_text = re.sub(r"добавь задачу", "", task_text, flags=re.IGNORECASE)
    task_text = re.sub(r"запиши задачу", "", task_text, flags=re.IGNORECASE)
    task_text = re.sub(r"создай задачу", "", task_text, flags=re.IGNORECASE)
    task_text = re.sub(r"поставь задачу", "", task_text, flags=re.IGNORECASE)
    task_text = re.sub(r"напомни мне", "", task_text, flags=re.IGNORECASE)
    task_text = re.sub(r"напомни", "", task_text, flags=re.IGNORECASE)
    task_text = re.sub(r"напомнить", "", task_text, flags=re.IGNORECASE)

    task_text = re.sub(r"\bсегодня\b", "", task_text, flags=re.IGNORECASE)
    task_text = re.sub(r"\bзавтра\b", "", task_text, flags=re.IGNORECASE)
    task_text = re.sub(r"\bпослезавтра\b", "", task_text, flags=re.IGNORECASE)
    task_text = re.sub(r"через\s+\d+\s+д\w*", "", task_text, flags=re.IGNORECASE)
    task_text = re.sub(r"через\s+\d+\s+нед\w*", "", task_text, flags=re.IGNORECASE)
    task_text = re.sub(r"через\s+\d+\s+мес\w*", "", task_text, flags=re.IGNORECASE)
    task_text = re.sub(r"через\s+месяц", "", task_text, flags=re.IGNORECASE)
    task_text = re.sub(r"\b\d{1,2}\.\d{1,2}(?:\.\d{2,4})?\b", "", task_text)

    if task_time:
        task_text = re.sub(r"\bв\s*\d{1,2}:\d{2}\b", "", task_text, flags=re.IGNORECASE)
        task_text = re.sub(r"\d{1,2}:\d{2}", "", task_text)

    task_text = task_text.strip()

    if not task_text:
        return None

    return task_text, task_date, task_time


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


def get_user_active_tasks(user_id):
    tasks = load_tasks()
    result = []

    for index, task in enumerate(tasks):
        if task.get("user_id") == user_id and task.get("status", "active") == "active":
            result.append((index, task))

    return result


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
        and any(word in text for word in [
            "удали", "удалить", "убери", "убрать", "отмени", "отменить", "отмена"
        ])
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
    active_tasks = get_user_active_tasks(user_id)

    if not active_tasks:
        return None

    if "последн" in text.lower():
        index, task = active_tasks[-1]
        deleted_task = tasks.pop(index)
        save_tasks(tasks)
        return deleted_task

    task_number = extract_task_number(text)

    if task_number and 1 <= task_number <= len(active_tasks):
        index, task = active_tasks[task_number - 1]
        deleted_task = tasks.pop(index)
        save_tasks(tasks)
        return deleted_task

    query = normalize_text(clean_task_command_text(text))

    if query:
        for index, task in active_tasks:
            title = normalize_text(task.get("title", ""))

            if query in title or title in query:
                deleted_task = tasks.pop(index)
                save_tasks(tasks)
                return deleted_task

    return None


def complete_task_by_text(user_id, text):
    tasks = load_tasks()
    active_tasks = get_user_active_tasks(user_id)

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


def get_today_tasks(user_id):
    tasks = load_tasks()

    return [
        task for task in tasks
        if task.get("user_id") == user_id
        and task.get("date") == get_today()
        and task.get("status", "active") == "active"
    ]


def calculate_balance(user_id):
    finance = load_finance()
    user_finance = [item for item in finance if item.get("user_id") == user_id]

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

    if period == "today":
        return today

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
        if item.get("user_id") != user_id:
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

    if stats["expense_by_category"]:
        text += "\nРасходы по категориям:\n"
        for category, amount in sorted(
            stats["expense_by_category"].items(),
            key=lambda x: abs(x[1]),
            reverse=True,
        ):
            text += f"• {category}: {amount}\n"

    if stats["income_by_category"]:
        text += "\nДоходы по категориям:\n"
        for category, amount in sorted(
            stats["income_by_category"].items(),
            key=lambda x: abs(x[1]),
            reverse=True,
        ):
            text += f"• {category}: +{amount}\n"

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
                "Если пользователь спрашивает точные финансы или задачи, не выдумывай данные. "
                "Отвечай просто, коротко, по-человечески. "
                "Без markdown, без звездочек, без цитат."
            ),
        }
    ]

    for item in get_memory(user_id):
        messages.append(item)

    messages.append({
        "role": "user",
        "content": text,
    })

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
    await message.answer(
        "Привет 💫 Я твой умный ассистент",
        reply_markup=main_keyboard,
    )


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
            await message.answer("На сегодня задач пока нет.")
        else:
            response = "📅 Задачи на сегодня:\n\n"

            for index, task in enumerate(tasks, start=1):
                task_time = f" ({task['time']})" if task.get("time") else ""
                response += f"{index}. {task['title']}{task_time}\n"

            await message.answer(response)

        return

    if text == "➕ Добавить задачу":
        user_states[user_id] = "task"
        await message.answer("Напиши задачу. Например: купить хлеб завтра в 18:00")
        return

    if user_states.get(user_id) == "task":
        task_time = extract_time(text)
        task_date = extract_date(text)

        title = text
        title = re.sub(r"\bсегодня\b", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\bзавтра\b", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\bпослезавтра\b", "", title, flags=re.IGNORECASE)
        title = re.sub(r"через\s+\d+\s+д\w*", "", title, flags=re.IGNORECASE)
        title = re.sub(r"через\s+\d+\s+нед\w*", "", title, flags=re.IGNORECASE)
        title = re.sub(r"через\s+\d+\s+мес\w*", "", title, flags=re.IGNORECASE)
        title = re.sub(r"через\s+месяц", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\b\d{1,2}\.\d{1,2}(?:\.\d{2,4})?\b", "", title)

        if task_time:
            title = re.sub(r"\bв\s*\d{1,2}:\d{2}\b", "", title, flags=re.IGNORECASE)
            title = re.sub(r"\d{1,2}:\d{2}", "", title)

        title = title.strip()

        add_task(user_id, title, task_date, task_time)
        user_states[user_id] = None

        if task_time:
            await message.answer(f"Добавила задачу: {title}\nНапомню {task_date} в {task_time}")
        else:
            await message.answer(f"Добавила задачу: {title}")

        return

    if text == "📋 Мои задачи":
        tasks = load_tasks()
        user_tasks = [task for task in tasks if task.get("user_id") == user_id]

        if not user_tasks:
            await message.answer("У тебя пока нет задач.")
        else:
            response = "📋 Все задачи:\n\n"

            for index, task in enumerate(user_tasks, start=1):
                status = "✅" if task.get("status") == "done" else "🟡"
                task_date = task.get("date", "")
                task_time = task.get("time", "")
                datetime_text = f" ({task_date} {task_time})" if task_time else f" ({task_date})"
                response += f"{index}. {status} {task['title']}{datetime_text}\n"

            await message.answer(response)

        return

    if detect_delete_task(text):
        deleted_task = delete_task_by_text(user_id, text)

        if deleted_task:
            await message.answer(f"Убрала задачу: {deleted_task['title']}")
        else:
            await message.answer("Не нашла такую активную задачу.")

        return

    if detect_complete_task(text):
        completed_task = complete_task_by_text(user_id, text)

        if completed_task:
            await message.answer(f"Отметила выполненной: {completed_task['title']}")
        else:
            await message.answer("Не нашла такую активную задачу.")

        return

    if text == "💰 Финансы":
        user_states[user_id] = "money"
        await message.answer("Напиши доход или расход. Например: -500 кофе или +1000 зарплата")
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
        return

    if text == "📊 Баланс" or detect_balance_question(text):
        balance, income, expense = calculate_balance(user_id)

        await message.answer(
            f"📊 Баланс: {balance}\n\n"
            f"Сегодня:\n"
            f"💚 Доходы: +{income}\n"
            f"💸 Расходы: {expense}"
        )
        return

    if text == "📈 Аналитика финансов":
        await message.answer(format_finance_stats(user_id, "today"))
        return

    finance_period = detect_finance_question(text)

    if finance_period:
        await message.answer(format_finance_stats(user_id, finance_period))
        return

    task_data = parse_smart_task(text)

    if task_data:
        title, task_date, task_time = task_data
        add_task(user_id, title, task_date, task_time)

        if task_time:
            await message.answer(f"Добавила задачу: {title}\nНапомню {task_date} в {task_time}")
        else:
            await message.answer(f"Добавила задачу: {title}")

        return

    finance_data = parse_smart_finance(text)

    if finance_data:
        amount, category = finance_data
        add_finance_operation(user_id, amount, category)
        await message.answer(f"Записала: {amount} ({category})")
        return

    await send_ai(message, text)


async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    asyncio.create_task(reminder_loop())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
