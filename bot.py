import asyncio
import os
import re
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = "8468979285:AAGz8Zq3N1F01XjFWxTfDfWuOPHGRTAjEjY"
API_ID = 34910343          # с my.telegram.org
API_HASH = "d20860d195501ba0993b794f952b1ef1" # с my.telegram.org

SESSIONS_DIR = Path("sessions")
SESSIONS_DIR.mkdir(exist_ok=True)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ================== СОСТОЯНИЯ ==================
class SessionStates(StatesGroup):
    waiting_session = State()

# ================== КЛАВИАТУРА ==================
def get_code_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📩 Получить код", callback_data="get_code")
    builder.button(text="🗑 Удалить сессию", callback_data="delete_session")
    builder.adjust(1)
    return builder.as_markup()

# ================== ОБРАБОТЧИКИ ==================
@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет!\n"
        "Отправь мне файл <b>.session</b>, и я смогу доставать из него коды входа.",
        parse_mode="HTML"
    )
    await state.set_state(SessionStates.waiting_session)

@dp.message(SessionStates.waiting_session, F.document)
async def receive_session(message: Message, state: FSMContext):
    document = message.document

    if not document.file_name.endswith(".session"):
        await message.answer("Пришли именно файл с расширением <b>.session</b>", parse_mode="HTML")
        return

    user_id = message.from_user.id
    session_path = SESSIONS_DIR / f"{user_id}.session"

    # Скачиваем файл
    await bot.download(document, destination=session_path)

    await state.update_data(session_path=str(session_path))
    await state.set_state(None)

    await message.answer(
        f"✅ Сессия сохранена: <code>{document.file_name}</code>\n\n"
        "Теперь можешь получать коды:",
        reply_markup=get_code_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "get_code")
async def get_code_handler(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    session_path = data.get("session_path")

    if not session_path or not Path(session_path).exists():
        await callback.answer("Сессия не найдена. Пришли .session заново.", show_alert=True)
        return

    await callback.answer("Ищу код...")

    try:
        client = TelegramClient(session_path, API_ID, API_HASH)
        await client.connect()

        if not await client.is_user_authorized():
            await callback.message.answer("❌ Сессия не авторизована / протухла")
            await client.disconnect()
            return

        # Ищем сообщения от официального Telegram (777000)
        code = None
        async for message in client.iter_messages(777000, limit=15):
            if message.message:
                # Ищем 5-значный или 6-значный код
                match = re.search(r'\b(\d{5,6})\b', message.message)
                if match:
                    code = match.group(1)
                    break

        await client.disconnect()

        if code:
            await callback.message.answer(
                f"🔑 <b>Код найден:</b>\n\n"
                f"<code>{code}</code>",
                parse_mode="HTML",
                reply_markup=get_code_keyboard()
            )
        else:
            await callback.message.answer(
                "Код не найден в последних сообщениях от Telegram.\n"
                "Попробуй запросить код ещё раз в клиенте и нажми кнопку снова.",
                reply_markup=get_code_keyboard()
            )

    except SessionPasswordNeededError:
        await callback.message.answer(
            "⚠️ На аккаунте включена 2FA (облачный пароль).\n"
            "Этот бот умеет доставать только обычный код из уведомлений.",
            reply_markup=get_code_keyboard()
        )
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: <code>{e}</code>", parse_mode="HTML")

@dp.callback_query(F.data == "delete_session")
async def delete_session_handler(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    session_path = data.get("session_path")

    if session_path and Path(session_path).exists():
        Path(session_path).unlink(missing_ok=True)

    await state.clear()
    await callback.message.edit_text("Сессия удалена. Пришли новый .session файл.")
    await state.set_state(SessionStates.waiting_session)
    await callback.answer()

# ================== ЗАПУСК ==================
async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
