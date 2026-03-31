import os
import re
from datetime import datetime, timedelta

from agents import Runner, trace
from dotenv import load_dotenv
from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from agent_setup import build_manager_agent
from google_calendar import (
    cancel_meeting as cancel_meeting_impl,
    get_available_time as get_available_time_impl,
    get_available_time_next_week as get_available_time_next_week_impl,
    get_available_time_this_week as get_available_time_this_week_impl,
    get_client_meetings as get_client_meetings_impl,
)

load_dotenv()
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MAX_HISTORY_TURNS = 10

_busy_chats: set[int] = set()
BUTTON_THIS_WEEK = "Вільний час на цьому тижні"
BUTTON_NEXT_WEEK = "Вільний час на наступному тижні"
BUTTON_ON_DATE = "Вільний час на дату"
BUTTON_CANCEL = "Відмінити запис"


def _trim_history(items: list) -> list:
    user_indices = [
        i for i, item in enumerate(items)
        if (isinstance(item, dict) and item.get("role") == "user")
        or (not isinstance(item, dict) and getattr(item, "role", None) == "user")
    ]
    if len(user_indices) <= MAX_HISTORY_TURNS:
        return items
    cutoff = user_indices[-MAX_HISTORY_TURNS]
    return items[cutoff:]


def _is_valid_email(text: str) -> bool:
    return re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text.strip()) is not None

START_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("▶️ Старт")]],
    resize_keyboard=True,
    one_time_keyboard=True,
)

ONBOARDING_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("⛔ Зупинити")]],
    resize_keyboard=True,
)

ACTION_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton(BUTTON_THIS_WEEK), KeyboardButton(BUTTON_NEXT_WEEK)],
        [KeyboardButton(BUTTON_ON_DATE), KeyboardButton(BUTTON_CANCEL)],
        [KeyboardButton("⛔ Зупинити")],
    ],
    resize_keyboard=True,
)


def _format_availability(payload: dict) -> str:
    def fmt_date(value: str) -> str:
        try:
            return datetime.strptime(value, "%Y-%m-%d").strftime("%d-%m-%Y")
        except ValueError:
            return value

    def fmt_slot(slot: str) -> str:
        if "-" not in slot:
            return slot
        start, end = slot.split("-", 1)
        try:
            start_dt = datetime.strptime(start, "%H:%M")
            end_dt = datetime.strptime(end, "%H:%M")
            if end_dt - start_dt == timedelta(hours=1):
                return start
        except ValueError:
            pass
        return slot

    days = payload.get("days")
    if isinstance(days, list):
        lines = []
        for day in days:
            date_iso = day.get("date", "")
            slots = day.get("available_slots", [])
            if slots:
                lines.append(f"{fmt_date(date_iso)}: {', '.join(fmt_slot(s) for s in slots)}")
            else:
                lines.append(f"{fmt_date(date_iso)}: немає вільного часу")
        return "\n".join(lines)
    slots = payload.get("available_slots", [])
    date_iso = payload.get("date", "")
    if slots:
        return f"{fmt_date(date_iso)}: {', '.join(fmt_slot(s) for s in slots)}"
    return f"{fmt_date(date_iso)}: немає вільного часу"


def _format_meetings(payload: dict) -> str:
    meetings = payload.get("meetings", [])
    if not meetings:
        return "У вас немає запланованих зустрічей для скасування."
    lines = ["Ваші зустрічі:"]
    for item in meetings:
        lines.append(f"- {item.get('start', '')} | {item.get('summary', '')} | ID: {item.get('id', '')}")
    lines.append("Надішліть ID зустрічі, яку потрібно скасувати.")
    return "\n".join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    context.chat_data["awaiting_name"] = True
    context.chat_data["awaiting_email"] = False
    await update.message.reply_text(
        "Вітаю! Це бот запису до психолога.\nБудь ласка, напишіть ваше ім'я.",
        reply_markup=ONBOARDING_KEYBOARD,
    )


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None:
        return

    if update.message.text == "▶️ Старт":
        context.chat_data["awaiting_name"] = True
        context.chat_data["awaiting_email"] = False
        await update.message.reply_text(
            "Вітаю! Це бот запису до психолога.\nБудь ласка, напишіть ваше ім'я.",
            reply_markup=ONBOARDING_KEYBOARD,
        )
        return

    if update.message.text == "⛔ Зупинити":
        context.chat_data["history"] = []
        context.chat_data.pop("client_name", None)
        context.chat_data.pop("client_email", None)
        context.chat_data.pop("awaiting_name", None)
        context.chat_data.pop("awaiting_email", None)
        context.chat_data.pop("awaiting_date_availability", None)
        context.chat_data.pop("awaiting_cancel_id", None)
        await update.message.reply_text(
            "Бота зупинено. Натисніть «▶️ Старт», щоб розпочати знову.",
            reply_markup=START_KEYBOARD,
        )
        return

    if context.chat_data.get("awaiting_name"):
        name = update.message.text.strip()
        if not name:
            await update.message.reply_text("Ім'я не може бути порожнім. Будь ласка, напишіть ваше ім'я.")
            return
        context.chat_data["client_name"] = name
        context.chat_data["awaiting_name"] = False
        context.chat_data["awaiting_email"] = True
        await update.message.reply_text(
            "Дякую! Тепер, будь ласка, напишіть ваш email.",
            reply_markup=ONBOARDING_KEYBOARD,
        )
        return

    if context.chat_data.get("awaiting_email"):
        email = update.message.text.strip()
        if not _is_valid_email(email):
            await update.message.reply_text("Некоректний email. Будь ласка, введіть email у форматі name@example.com.")
            return
        context.chat_data["client_email"] = email
        context.chat_data["awaiting_email"] = False
        await update.message.reply_text(
            "Дякую! Дані збережено. Тепер надішліть бажану дату і час консультації.",
            reply_markup=ACTION_KEYBOARD,
        )
        return

    if not context.chat_data.get("client_name") or not context.chat_data.get("client_email"):
        context.chat_data["awaiting_name"] = True
        context.chat_data["awaiting_email"] = False
        await update.message.reply_text("Перед записом, будь ласка, напишіть ваше ім'я.")
        return

    client_email = context.chat_data.get("client_email", "")

    if update.message.text == BUTTON_THIS_WEEK:
        payload = get_available_time_this_week_impl()
        await update.message.reply_text(_format_availability(payload))
        return

    if update.message.text == BUTTON_NEXT_WEEK:
        payload = get_available_time_next_week_impl()
        await update.message.reply_text(_format_availability(payload))
        return

    if update.message.text == BUTTON_ON_DATE:
        context.chat_data["awaiting_date_availability"] = True
        await update.message.reply_text("Вкажіть дату у форматі DD-MM-YYYY.")
        return

    if context.chat_data.get("awaiting_date_availability"):
        context.chat_data["awaiting_date_availability"] = False
        try:
            payload = get_available_time_impl(update.message.text.strip(), 60)
            await update.message.reply_text(_format_availability(payload))
        except Exception:
            await update.message.reply_text("Не вдалося розпізнати дату. Формат: DD-MM-YYYY.")
        return

    if update.message.text == BUTTON_CANCEL:
        payload = get_client_meetings_impl(client_email=client_email, max_results=20)
        context.chat_data["awaiting_cancel_id"] = True
        await update.message.reply_text(_format_meetings(payload))
        return

    if context.chat_data.get("awaiting_cancel_id"):
        event_id = update.message.text.strip()
        try:
            cancel_meeting_impl(event_id=event_id, client_email=client_email)
            context.chat_data["awaiting_cancel_id"] = False
            await update.message.reply_text("Запис скасовано.")
        except Exception:
            await update.message.reply_text("Не вдалося скасувати запис. Перевірте ID і спробуйте ще раз.")
        return

    chat_id = update.effective_chat.id

    if chat_id in _busy_chats:
        await update.message.reply_text("⏳ Зачекайте, обробляю попередній запит.")
        return

    _busy_chats.add(chat_id)
    status_msg = await update.message.reply_text("⏳ Обробляю...")

    try:
        agent = build_manager_agent(model=MODEL)
        history = context.chat_data.get("history", [])
        client_name = context.chat_data.get("client_name")
        user_content = update.message.text
        if client_name and client_email:
            user_content = (
                f"Дані клієнта для запису: ім'я={client_name}, email={client_email}.\n"
                f"Назва зустрічі повинна бути: Зустріч з {client_name}.\n"
                f"Запит клієнта: {update.message.text}"
            )
        history.append({"role": "user", "content": user_content})
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                with trace("calendar-agent-telegram"):
                    result = await Runner.run(agent, history)
                assistant_text = str(result.final_output)
                full_history = _trim_history(result.to_input_list())
                context.chat_data["history"] = full_history
                await status_msg.edit_text(assistant_text)
                last_error = None
                break
            except Exception as e:
                last_error = e
                if attempt == 0:
                    await status_msg.edit_text("⏳ Повторна спроба...")
        if last_error is not None:
            await status_msg.edit_text(
                "Виникла тимчасова помилка. Спробуйте надіслати запит ще раз."
            )
    finally:
        _busy_chats.discard(chat_id)


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()


if __name__ == "__main__":
    main()
