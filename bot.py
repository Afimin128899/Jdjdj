import asyncio
import re
import shutil
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

from opentele.td import TDesktop
from opentele.tl import TelegramClient
from opentele.api import API, UseCurrentSession
from telethon.errors import SessionPasswordNeededError

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = "8468979285:AAGz8Zq3N1F01XjFWxTfDfWuOPHGRTAjEjY"
API_ID = 34910343
API_HASH = "d20860d195501ba0993b794f952b1ef1"

TDATA_DIR = Path("tdatas")
TDATA_DIR.mkdir(exist_ok=True)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class SessionStates(StatesGroup):
    waiting_tdata = State()

def get_code_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📩 Получить код", callback_data="get_code")
    builder.button(text="🗑 Удалить tdata", callback_data="delete_tdata")
    builder.adjust(1)
    return builder.as_markup()

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет!\n"
        "Пришли мне папку <b>tdata</b> в виде архива (.zip) или просто напиши путь, "
        "но лучше всего — заархивируй tdata и отправь файл.",
        parse_mode="HTML"
    )
    await state.set_state(SessionStates.waiting_tdata)

@dp.message(SessionStates.waiting_tdata, F.document)
async def receive_tdata(message: Message, state: FSMContext):
    document = message.document
    user_id = message.from_user.id

    # Сохраняем архив
    archive_path = TDATA_DIR / f"{user_id}.zip"
    await bot.download(document, destination=archive_path)

    # Распаковываем
    extract_path = TDATA_DIR / str(user_id)
    if extract_path.exists():
        shutil.rmtree(extract_path)
    extract_path.mkdir()

    try:
        shutil.unpack_archive(archive_path, extract_path)
    except Exception as e:
        await message.answer(f"Не удалось распаковать архив: {e}")
        return

    # Ищем папку tdata внутри
    tdata_path = None
    for item in extract_path.rglob("*"):
        if item.is_dir() and item.name.lower() == "tdata":
            tdata_path = item
            break

    if not tdata_path:
        # Возможно пользователь прислал саму tdata без обёртки
        if (extract_path / "key_datas").exists() or (extract_path / "map0").exists():
            tdata_path = extract_path
        else:
            await message.answer("Не нашёл папку tdata внутри архива.")
            return

    await state.update_data(tdata_path=str(tdata_path))
    await state.set_state(None)

    await message.answer(
        f"✅ tdata сохранена\n\nТеперь можно получать коды:",
        reply_markup=get_code_keyboard()
    )

@dp.callback_query(F.data == "get_code")
async def get_code_handler(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    tdata_path = data.get("tdata_path")

    if not tdata_path or not Path(tdata_path).exists():
        await callback.answer("tdata не найдена", show_alert=True)
        return

    await callback.answer("Ищу код...")

    try:
        # Загружаем tdata
        tdesk = TDesktop(tdata_path)
        
        if not tdesk.isLoaded():
            await callback.message.answer("❌ Не удалось загрузить tdata")
            return

        # Создаём клиент из tdata
        client = await tdesk.ToTelethon(
            session=f"sessions/{callback.from_user.id}",
            flag=UseCurrentSession,
            api=API.TelegramDesktop
        )

        await client.connect()

        if not await client.is_user_authorized():
            await callback.message.answer("❌ Сессия из tdata не авторизована")
            await client.disconnect()
            return

        # Ищем код
        code = None
        async for msg in client.iter_messages(777000, limit=30):
            if msg.message:
                match = re.search(r'\b(\d{5,6})\b', msg.message)
                if match:
                    code = match.group(1)
                    break

        await client.disconnect()

        if code:
            await callback.message.answer(
                f"🔑 <b>Код:</b>\n<code>{code}</code>",
                parse_mode="HTML",
                reply_markup=get_code_keyboard()
            )
        else:
            await callback.message.answer(
                "Код не найден. Запроси код заново и нажми кнопку.",
                reply_markup=get_code_keyboard()
            )

    except SessionPasswordNeededError:
        await callback.message.answer(
            "На аккаунте стоит 2FA (облачный пароль).",
            reply_markup=get_code_keyboard()
        )
    except Exception as e:
        await callback.message.answer(
            f"❌ Ошибка: <code>{e}</code>",
            parse_mode="HTML",
            reply_markup=get_code_keyboard()
        )

@dp.callback_query(F.data == "delete_tdata")
async def delete_tdata_handler(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    tdata_path = data.get("tdata_path")

    if tdata_path and Path(tdata_path).exists():
        # Удаляем всю папку пользователя
        user_folder = Path(tdata_path).parent
        shutil.rmtree(user_folder, ignore_errors=True)

    await state.clear()
    await callback.message.edit_text("tdata удалена. Пришли новую.")
    await state.set_state(SessionStates.waiting_tdata)
    await callback.answer()

async def main():
    print("Бот запущен (через tdata + opentele)")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
