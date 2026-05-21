import telebot
from telebot import types
import logging
import os
from dotenv import load_dotenv

import db_handler as db
import analyzer

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "8471506864:AAFfupmZDgTYPHdOo64_3IYhXpBTPaacQFs")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

user_states: dict[int, dict] = {}

STATE_IDLE          = "idle"
STATE_MOOD          = "awaiting_mood"
STATE_STUDY         = "awaiting_study_hours"
STATE_STUDY_CUSTOM  = "awaiting_study_custom"
STATE_SLEEP         = "awaiting_sleep_hours"
STATE_SLEEP_CUSTOM  = "awaiting_sleep_custom"
STATE_COMMENT       = "awaiting_comment"
STATE_CLEAR_CONFIRM = "awaiting_clear_confirm"
STATE_REMIND_TIME   = "awaiting_reminder_time"


def get_state(uid: int) -> str:
    return user_states.get(uid, {}).get("state", STATE_IDLE)


def set_state(uid: int, state: str, **data):
    if uid not in user_states:
        user_states[uid] = {}
    user_states[uid]["state"] = state
    user_states[uid].update(data)


def clear_state(uid: int):
    user_states.pop(uid, None)


def main_menu_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton("➕ Записать день"),
        types.KeyboardButton("📊 Статистика"),
        types.KeyboardButton("📋 История"),
        types.KeyboardButton("⚙️ Настройки"),
    )
    return kb


@bot.message_handler(commands=["start"])
def cmd_start(msg: types.Message):
    db.ensure_user(msg.from_user.id, msg.from_user.username or "")
    text = (
        "👋 <b>Привет! Я — твой личный трекер настроения и продуктивности.</b>\n\n"
        "Каждый день я буду спрашивать тебя о трёх простых вещах:\n"
        "  🌤 <b>Настроение</b> (1–5)\n"
        "  📚 <b>Часы учёбы / работы</b>\n"
        "  😴 <b>Часы сна</b>\n\n"
        "На основе накопленных данных я найду скрытые закономерности и помогу тебе "
        "лучше понять себя.\n\n"
        "Нажми <b>➕ Записать день</b>, чтобы начать!"
    )
    bot.send_message(msg.chat.id, text, reply_markup=main_menu_kb())


@bot.message_handler(commands=["help"])
def cmd_help(msg: types.Message):
    text = (
        "📖 <b>Справка</b>\n\n"
        "/start — Приветствие\n"
        "/add — Записать сегодняшний день\n"
        "/stats — Статистика\n"
        "/history — История записей\n"
        "/settings — Настройки напоминаний\n"
        "/clear — Очистить все данные\n"
        "/help — Эта справка"
    )
    bot.send_message(msg.chat.id, text, reply_markup=main_menu_kb())

def start_add_flow(chat_id: int, user_id: int):
    db.ensure_user(user_id, "")
    set_state(user_id, STATE_MOOD)
    kb = types.InlineKeyboardMarkup(row_width=5)
    emojis = {1: "😞", 2: "😐", 3: "🙂", 4: "😊", 5: "🤩"}
    buttons = [
        types.InlineKeyboardButton(f"{v} {k}", callback_data=f"mood:{k}")
        for k, v in emojis.items()
    ]
    kb.add(*buttons)
    bot.send_message(
        chat_id,
        "📝 <b>Шаг 1 / 4 — Настроение</b>\n\nОцени своё настроение сегодня:",
        reply_markup=kb,
    )


@bot.message_handler(commands=["add"])
def cmd_add(msg: types.Message):
    start_add_flow(msg.chat.id, msg.from_user.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("mood:"))
def cb_mood(call: types.CallbackQuery):
    uid = call.from_user.id
    if get_state(uid) != STATE_MOOD:
        bot.answer_callback_query(call.id, "Сначала нажми /add")
        return
    score = int(call.data.split(":")[1])
    set_state(uid, STATE_STUDY, mood=score)
    bot.answer_callback_query(call.id)
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id)

    kb = types.InlineKeyboardMarkup(row_width=5)
    hours = ["0.5", "1", "2", "4", "6"]
    buttons = [types.InlineKeyboardButton(f"{h} ч", callback_data=f"study:{h}") for h in hours]
    buttons.append(types.InlineKeyboardButton("✏️ Другое...", callback_data="study:custom"))
    kb.add(*buttons)
    bot.send_message(
        call.message.chat.id,
        f"✅ Настроение: <b>{score}/5</b>\n\n"
        "📚 <b>Шаг 2 / 4 — Учёба / работа</b>\n\nСколько часов ты потратил на продуктивную работу?",
        reply_markup=kb,
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("study:"))
def cb_study(call: types.CallbackQuery):
    uid = call.from_user.id
    if get_state(uid) != STATE_STUDY:
        bot.answer_callback_query(call.id)
        return
    bot.answer_callback_query(call.id)
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id)
    val = call.data.split(":")[1]
    if val == "custom":
        set_state(uid, STATE_STUDY_CUSTOM, mood=user_states[uid]["mood"])
        bot.send_message(call.message.chat.id, "✏️ Введи количество часов (например: <b>3.5</b>):")
    else:
        set_state(uid, STATE_SLEEP, mood=user_states[uid]["mood"], study_hours=float(val))
        _ask_sleep(call.message.chat.id, float(val))


def _ask_sleep(chat_id: int, study_hours: float):
    kb = types.InlineKeyboardMarkup(row_width=5)
    hours = ["5", "6", "7", "8", "9"]
    buttons = [types.InlineKeyboardButton(f"{h} ч", callback_data=f"sleep:{h}") for h in hours]
    buttons.append(types.InlineKeyboardButton("✏️ Другое...", callback_data="sleep:custom"))
    kb.add(*buttons)
    bot.send_message(
        chat_id,
        f"✅ Учёба/работа: <b>{study_hours} ч</b>\n\n"
        "😴 <b>Шаг 3 / 4 — Сон</b>\n\nСколько часов ты спал?",
        reply_markup=kb,
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("sleep:"))
def cb_sleep(call: types.CallbackQuery):
    uid = call.from_user.id
    if get_state(uid) != STATE_SLEEP:
        bot.answer_callback_query(call.id)
        return
    bot.answer_callback_query(call.id)
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id)
    val = call.data.split(":")[1]
    if val == "custom":
        set_state(uid, STATE_SLEEP_CUSTOM,
                  mood=user_states[uid]["mood"],
                  study_hours=user_states[uid]["study_hours"])
        bot.send_message(call.message.chat.id, "✏️ Введи количество часов сна (например: <b>7.5</b>):")
    else:
        sleep_hours = float(val)
        set_state(uid, STATE_COMMENT,
                  mood=user_states[uid]["mood"],
                  study_hours=user_states[uid]["study_hours"],
                  sleep_hours=sleep_hours)
        _ask_comment(call.message.chat.id, sleep_hours)


def _ask_comment(chat_id: int, sleep_hours: float):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⏩ Пропустить", callback_data="comment:skip"))
    bot.send_message(
        chat_id,
        f"✅ Сон: <b>{sleep_hours} ч</b>\n\n"
        "💬 <b>Шаг 4 / 4 — Комментарий (необязательно)</b>\n\n"
        "Напиши заметку о сегодняшнем дне или нажми «Пропустить»:",
        reply_markup=kb,
    )


@bot.callback_query_handler(func=lambda c: c.data == "comment:skip")
def cb_comment_skip(call: types.CallbackQuery):
    uid = call.from_user.id
    bot.answer_callback_query(call.id)
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id)
    _save_entry(call.message.chat.id, uid, comment=None)


@bot.message_handler(func=lambda m: get_state(m.from_user.id) == STATE_STUDY_CUSTOM)
def msg_study_custom(msg: types.Message):
    uid = msg.from_user.id
    try:
        hours = float(msg.text.replace(",", "."))
        if not (0 <= hours <= 24):
            raise ValueError
    except ValueError:
        bot.send_message(msg.chat.id, "⚠️ Введи корректное число от 0 до 24.")
        return
    set_state(uid, STATE_SLEEP, mood=user_states[uid]["mood"], study_hours=hours)
    _ask_sleep(msg.chat.id, hours)


@bot.message_handler(func=lambda m: get_state(m.from_user.id) == STATE_SLEEP_CUSTOM)
def msg_sleep_custom(msg: types.Message):
    uid = msg.from_user.id
    try:
        hours = float(msg.text.replace(",", "."))
        if not (0 <= hours <= 24):
            raise ValueError
    except ValueError:
        bot.send_message(msg.chat.id, "⚠️ Введи корректное число от 0 до 24.")
        return
    set_state(uid, STATE_COMMENT,
              mood=user_states[uid]["mood"],
              study_hours=user_states[uid]["study_hours"],
              sleep_hours=hours)
    _ask_comment(msg.chat.id, hours)


@bot.message_handler(func=lambda m: get_state(m.from_user.id) == STATE_COMMENT)
def msg_comment(msg: types.Message):
    uid = msg.from_user.id
    _save_entry(msg.chat.id, uid, comment=msg.text.strip())


def _save_entry(chat_id: int, uid: int, comment):
    s = user_states.get(uid, {})
    db.add_entry(
        user_id=uid,
        mood=s["mood"],
        study_hours=s["study_hours"],
        sleep_hours=s["sleep_hours"],
        comment=comment,
    )
    clear_state(uid)
    emojis = {1: "😞", 2: "😐", 3: "🙂", 4: "😊", 5: "🤩"}
    bot.send_message(
        chat_id,
        f"✅ <b>Запись сохранена!</b>\n\n"
        f"  Настроение: {emojis[s['mood']]} {s['mood']}/5\n"
        f"  Учёба/работа: {s['study_hours']} ч\n"
        f"  Сон: {s['sleep_hours']} ч\n"
        f"  Комментарий: {comment or '—'}\n\n"
        "Так держать! 💪",
        reply_markup=main_menu_kb(),
    )

def stats_menu_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📅 За неделю",  callback_data="stats:week"),
        types.InlineKeyboardButton("🗓 За месяц",   callback_data="stats:month"),
        types.InlineKeyboardButton("🔍 Инсайты",    callback_data="stats:insights"),
        types.InlineKeyboardButton("📉 Графики",    callback_data="stats:chart"),
    )
    return kb


@bot.message_handler(commands=["stats"])
def cmd_stats(msg: types.Message):
    bot.send_message(msg.chat.id, "📊 <b>Что хочешь узнать?</b>", reply_markup=stats_menu_kb())


@bot.callback_query_handler(func=lambda c: c.data.startswith("stats:"))
def cb_stats(call: types.CallbackQuery):
    uid = call.from_user.id
    bot.answer_callback_query(call.id)
    period = call.data.split(":")[1]

    if period == "week":
        text = analyzer.weekly_summary(uid)
    elif period == "month":
        text = analyzer.monthly_summary(uid)
    elif period == "insights":
        text = analyzer.insights(uid)
    elif period == "chart":
        buf = analyzer.mood_chart(uid)
        if buf:
            bot.send_photo(call.message.chat.id, buf, caption="📉 Динамика настроения за последние 30 дней")
        else:
            bot.send_message(call.message.chat.id, "⚠️ Недостаточно данных для графика.")
        return
    else:
        text = "Неизвестный раздел."

    bot.send_message(call.message.chat.id, text, reply_markup=stats_menu_kb())

@bot.message_handler(commands=["history"])
def cmd_history(msg: types.Message):
    rows = db.get_history(msg.from_user.id, limit=10)
    if not rows:
        bot.send_message(msg.chat.id, "📋 История пуста. Начни с /add")
        return
    emojis = {1: "😞", 2: "😐", 3: "🙂", 4: "😊", 5: "🤩"}
    lines = ["📋 <b>Последние 10 записей:</b>\n"]
    for r in rows:
        date_str, mood, study, sleep, comment = r
        lines.append(
            f"<b>{date_str}</b> — {emojis.get(mood,'?')} {mood}/5 | 📚 {study}ч | 😴 {sleep}ч"
            + (f"\n   💬 {comment}" if comment else "")
        )
    bot.send_message(msg.chat.id, "\n".join(lines), reply_markup=main_menu_kb())

@bot.message_handler(commands=["settings"])
def cmd_settings(msg: types.Message):
    uid = msg.from_user.id
    current_time = db.get_reminder_time(uid) or "не задано"
    set_state(uid, STATE_REMIND_TIME)
    bot.send_message(
        msg.chat.id,
        f"⚙️ <b>Настройки</b>\n\n"
        f"Текущее время напоминания: <b>{current_time}</b>\n\n"
        "Введи новое время в формате <b>ЧЧ:ММ</b> (например: <b>21:00</b>).\n"
        "Или нажми /cancel для отмены.",
    )


@bot.message_handler(func=lambda m: get_state(m.from_user.id) == STATE_REMIND_TIME)
def msg_reminder_time(msg: types.Message):
    uid = msg.from_user.id
    import re
    if not re.match(r"^\d{2}:\d{2}$", msg.text.strip()):
        bot.send_message(msg.chat.id, "⚠️ Формат: ЧЧ:ММ, например 21:30")
        return
    db.set_reminder_time(uid, msg.text.strip())
    clear_state(uid)
    bot.send_message(
        msg.chat.id,
        f"✅ Напоминание установлено на <b>{msg.text.strip()}</b>",
        reply_markup=main_menu_kb(),
    )

@bot.message_handler(commands=["clear"])
def cmd_clear(msg: types.Message):
    set_state(msg.from_user.id, STATE_CLEAR_CONFIRM)
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("⚠️ Да, удалить всё", callback_data="clear:yes"),
        types.InlineKeyboardButton("❌ Отмена",           callback_data="clear:no"),
    )
    bot.send_message(
        msg.chat.id,
        "🗑 <b>Удалить все данные?</b>\n\nЭто действие <b>нельзя отменить</b>.",
        reply_markup=kb,
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("clear:"))
def cb_clear(call: types.CallbackQuery):
    uid = call.from_user.id
    bot.answer_callback_query(call.id)
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id)
    if call.data == "clear:yes" and get_state(uid) == STATE_CLEAR_CONFIRM:
        db.clear_user_data(uid)
        clear_state(uid)
        bot.send_message(call.message.chat.id, "✅ Все данные удалены.", reply_markup=main_menu_kb())
    else:
        clear_state(uid)
        bot.send_message(call.message.chat.id, "Отменено.", reply_markup=main_menu_kb())


@bot.message_handler(func=lambda m: m.text == "➕ Записать день")
def reply_add(msg): start_add_flow(msg.chat.id, msg.from_user.id)

@bot.message_handler(func=lambda m: m.text == "📊 Статистика")
def reply_stats(msg): cmd_stats(msg)

@bot.message_handler(func=lambda m: m.text == "📋 История")
def reply_history(msg): cmd_history(msg)

@bot.message_handler(func=lambda m: m.text == "⚙️ Настройки")
def reply_settings(msg): cmd_settings(msg)

@bot.message_handler(commands=["cancel"])
def cmd_cancel(msg: types.Message):
    clear_state(msg.from_user.id)
    bot.send_message(msg.chat.id, "Действие отменено.", reply_markup=main_menu_kb())

if __name__ == "__main__":
    db.init_db()
    logger.info("Bot is running...")
    bot.infinity_polling(logger_level=logging.INFO)