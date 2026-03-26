import os

from agents import Runner, trace
from dotenv import load_dotenv
from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from agent_setup import build_manager_agent

load_dotenv()
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MAX_HISTORY_TURNS = 10

_busy_chats: set[int] = set()


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

START_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("▶️ Старт")]],
    resize_keyboard=True,
    one_time_keyboard=True,
)

STOP_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("⛔ Зупинити")]],
    resize_keyboard=True,
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(
        "Привіт! Натисніть кнопку нижче, щоб розпочати.",
        reply_markup=START_KEYBOARD,
    )


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None:
        return

    if update.message.text == "▶️ Старт":
        await update.message.reply_text(
            "Асистент готовий. Надішліть запит щодо календаря.",
            reply_markup=STOP_KEYBOARD,
        )
        return

    if update.message.text == "⛔ Зупинити":
        context.chat_data["history"] = []
        await update.message.reply_text(
            "Бота зупинено. Натисніть «▶️ Старт», щоб розпочати знову.",
            reply_markup=START_KEYBOARD,
        )
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
        history.append({"role": "user", "content": update.message.text})
        with trace("calendar-agent-telegram"):
            result = await Runner.run(agent, history)
        assistant_text = str(result.final_output)
        full_history = _trim_history(result.to_input_list())
        context.chat_data["history"] = full_history
        await status_msg.edit_text(assistant_text)
    except Exception as e:
        await status_msg.edit_text(f"❌ Помилка: {e}")
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
