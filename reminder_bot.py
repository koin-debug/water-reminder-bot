import datetime
import json
import random
import threading
import time
from pathlib import Path

import telebot
from telebot import types

bot = telebot.TeleBot("BOT_TOKEN")

DATA_FILE = Path(__file__).parent / "user_data.json"
data_lock = threading.Lock()

WATER_FACTS = [
    "Вода на Земле может быть старше самой Солнечной системы: до 50% воды в океанах существовало в межзвёздном пространстве ещё 4,6 млрд лет назад.",
    "Горячая вода при определённых условиях может замерзать быстрее холодной — это явление известно как эффект Мпемба.",
    "В атмосфере Земли в виде водяного пара содержится больше воды, чем во всех реках мира вместе взятых.",
]


def load_data() -> dict[int, dict]:
    """Загружает данные пользователей из JSON-файла при старте бота.

    Returns:
        dict[int, dict]: Словарь с данными пользователей, где ключи приведены к int.
    """
    if not DATA_FILE.exists():
        return {}

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            raw_data = json.load(file)
            return {int(chat_id): info for chat_id, info in raw_data.items()}
    except (json.JSONDecodeError, ValueError):
        return {}


def save_data() -> None:
    """Сохраняет актуальный словарь user_data в JSON-файл."""
    with data_lock:
        serializable_data = {
            str(chat_id): {
                "count": info["count"],
                "date": info["date"],
                "schedule": info["schedule"],
                "last_reminded": info.get("last_reminded", ""),
            }
            for chat_id, info in user_data.items()
        }
        with open(DATA_FILE, "w", encoding="utf-8") as file:
            json.dump(serializable_data, file, ensure_ascii=False, indent=4)


user_data: dict[int, dict] = load_data()


def get_user_state(chat_id: int) -> dict:
    """Возвращает данные пользователя или создаёт настройки по умолчанию.

    Args:
        chat_id (int): Уникальный идентификатор чата в Telegram.

    Returns:
        dict: Словарь с актуальным счётчиком, датой, расписанием и меткой последнего уведомления.
    """
    today = datetime.date.today().isoformat()
    changed = False

    if chat_id not in user_data:
        user_data[chat_id] = {
            "count": 0,
            "date": today,
            "schedule": ["09:00", "14:00", "18:00"],
            "last_reminded": "",
            "started": False,
        }
        changed = True
    
    else:
        user_data[chat_id].setdefault("started", False)
        user_data[chat_id].setdefault("last_reminded", "")

        if user_data[chat_id]["date"] != today:
            user_data[chat_id]["count"] = 0
            user_data[chat_id]["date"] = today
            changed = True

    if changed:
        save_data()

    return user_data[chat_id]


def ensure_reminder_thread(chat_id: int) -> None:
    """Запускает фоновый поток напоминаний для пользователя, если он ещё не активен.

    Args:
        chat_id (int): Уникальный идентификатор чата пользователя.
    """
    state = get_user_state(chat_id)
    if not state["started"]:
        state["started"] = True
        reminder_thread = threading.Thread(
            target=send_reminders,
            args=(chat_id,),
            daemon=True,
        )
        reminder_thread.start()


def create_main_menu() -> types.ReplyKeyboardMarkup:
    """Создаёт нижнюю клавиатуру с основными кнопками управления.

    Returns:
        types.ReplyKeyboardMarkup: Готовый объект клавиатуры.
    """
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(
        types.KeyboardButton("💧 Факт о воде"),
        types.KeyboardButton("📊 Мой счётчик"),
    )
    markup.add(
        types.KeyboardButton("⏰ Расписание"),
        types.KeyboardButton("⚙️ Изменить расписание"),
    )
    return markup


def create_water_inline_button() -> types.InlineKeyboardMarkup:
    """Создаёт инлайн-кнопку подтверждения под сообщением-напоминанием.

    Returns:
        types.InlineKeyboardMarkup: Клавиатура с кнопкой под сообщением.
    """
    markup = types.InlineKeyboardMarkup()
    btn_done = types.InlineKeyboardButton(
        text="Выпил стакан ✅",
        callback_data="water_drunk",
    )
    markup.add(btn_done)
    return markup


def send_reminders(chat_id: int) -> None:
    """Отправляет напоминания о воде не более одного раза в запланированную минуту.

    Args:
        chat_id (int): Уникальный идентификатор чата пользователя в Telegram.
    """
    while True:
        state = get_user_state(chat_id)
        now_dt = datetime.datetime.now()
        current_time = now_dt.strftime("%H:%M")
        current_slot = now_dt.strftime("%Y-%m-%d %H:%M")

        # Отправляем только если время совпало и в эту минуту напоминания ещё не было
        if current_time in state["schedule"] and state["last_reminded"] != current_slot:
            try:
                bot.send_message(
                    chat_id,
                    "Напоминание: пора выпить стакан воды!",
                    reply_markup=create_water_inline_button(),
                )
                # Фиксируем отправленный слот в памяти и сразу записываем в JSON
                state["last_reminded"] = current_slot
                save_data()
            except Exception as error:  # noqa: BLE001
                print(f"Ошибка отправки пользователю {chat_id}: {error}")

        time.sleep(2)


def process_new_schedule(message: types.Message) -> None:
    """Проверяет введённое пользователем время, обновляет расписание и сохраняет в JSON.

    Args:
        message (types.Message): Сообщение пользователя со списком времени.
    """
    if not message.text:
        bot.send_message(message.chat.id, "Пожалуйста, отправь время текстом в формате ЧЧ:ММ.")
        return

    raw_times = [item.strip() for item in message.text.split(",") if item.strip()]
    valid_times: list[str] = []

    for time_str in raw_times:
        try:
            parsed = datetime.datetime.strptime(time_str, "%H:%M")
            valid_times.append(parsed.strftime("%H:%M"))
        except ValueError:
            bot.send_message(
                message.chat.id,
                f"❌ Неверный формат времени: «{time_str}».\n"
                "Нажми «⚙️ Изменить расписание» ещё раз и введи время через запятую, например:\n"
                "`09:00, 13:30, 18:00`",
                parse_mode="Markdown",
            )
            return

    if not valid_times:
        bot.send_message(message.chat.id, "Список пуст. Попробуй ещё раз через кнопку меню.")
        return

    state = get_user_state(message.chat.id)
    state["schedule"] = sorted(set(valid_times))
    save_data()

    bot.send_message(
        message.chat.id,
        f"✅ Расписание обновлено и сохранено! Новое время напоминаний:\n**{', '.join(state['schedule'])}**",
        parse_mode="Markdown",
        reply_markup=create_main_menu(),
    )


@bot.message_handler(commands=["start"])
def start_message(message: types.Message) -> None:
    """Обрабатывает команду /start, выводит меню и запускает фоновый поток.

    Args:
        message (types.Message): Объект входящего сообщения от пользователя.
    """
    get_user_state(message.chat.id)
    ensure_reminder_thread(message.chat.id)

    bot.send_message(
        message.chat.id,
        "Привет! Я твой трекер воды 💧\n"
        "Все твои настройки и счётчик теперь надёжно сохраняются.",
        reply_markup=create_main_menu(),
    )


@bot.message_handler(content_types=["text"])
def handle_menu_buttons(message: types.Message) -> None:
    """Обрабатывает нажатия на кнопки нижней клавиатуры.

    Args:
        message (types.Message): Объект текстового сообщения от пользователя.
    """
    state = get_user_state(message.chat.id)
    ensure_reminder_thread(message.chat.id)

    if message.text == "💧 Факт о воде":
        random_fact = random.choice(WATER_FACTS)
        bot.send_message(message.chat.id, f"Лови факт о воде:\n\n{random_fact}")

    elif message.text == "📊 Мой счётчик":
        bot.send_message(
            message.chat.id,
            f"Сегодня выпито стаканов: **{state['count']}** 💧",
            parse_mode="Markdown",
        )

    elif message.text == "⏰ Расписание":
        schedule_text = ", ".join(state["schedule"])
        bot.send_message(
            message.chat.id,
            f"Твоё текущее расписание напоминаний:\n**{schedule_text}**",
            parse_mode="Markdown",
        )

    elif message.text == "⚙️ Изменить расписание":
        msg = bot.send_message(
            message.chat.id,
            "Введи новое время напоминаний через запятую в формате `ЧЧ:ММ`.\n"
            "Например: `08:30, 12:00, 16:45, 20:00`",
            parse_mode="Markdown",
        )
        bot.register_next_step_handler(msg, process_new_schedule)


@bot.callback_query_handler(func=lambda call: call.data == "water_drunk")
def handle_water_callback(call: types.CallbackQuery) -> None:
    """Увеличивает дневной счётчик при нажатии на инлайн-кнопку и сохраняет в JSON.

    Args:
        call (types.CallbackQuery): Объект события нажатия на инлайн-кнопку.
    """
    state = get_user_state(call.message.chat.id)
    state["count"] += 1
    save_data()

    bot.answer_callback_query(call.id, text=f"Засчитано! Всего за день: {state['count']} 💧")

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=f"✅ Стакан воды выпит!\n📊 Выпито сегодня: **{state['count']}**",
        parse_mode="Markdown",
    )


if __name__ == "__main__":
    for saved_chat_id in list(user_data.keys()):
        ensure_reminder_thread(saved_chat_id)

    # infinity_polling автоматически ловит ReadTimeout и перезапускает опрос
    bot.infinity_polling(timeout=10, long_polling_timeout=5)