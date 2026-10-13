import asyncio
import re
import zipfile
import tempfile
import shutil
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

BOT_TOKEN = "8468979285:AAEdtVtNJt6UTXzpojrwY6aBOGnM1xSGEBA"
API_ID = 34910343
API_HASH = "d20860d195501ba0993b794f952b1ef1"

SESSIONS_DIR = Path("sessions")
SESSIONS_DIR.mkdir(exist_ok=True)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


class SessionStates(StatesGroup):
    waiting_session = State()


def get_code_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📩 Получить код", callback_data="get_code")
    builder.button(text="🗑 Удалить сессию", callback_data="delete_session")
    builder.adjust(1)
    return builder.as_markup()


def build_accounts_keyboard(accounts):
    builder = InlineKeyboardBuilder()
    for i, acc in enumerate(accounts):
        name = acc.get("name") or f"session_{i}"
        status = "✅" if acc.get("processed") else "⬜️"
        builder.button(text=f"{i + 1}. {name} {status}", callback_data=f"select:{i}")
    builder.button(text="Добавить ещё .session/.zip", callback_data="add_more")
    builder.adjust(1)
    return builder.as_markup()


def build_account_menu(index):
    builder = InlineKeyboardBuilder()
    builder.button(text="📩 Получить код", callback_data=f"getcode:{index}")
    builder.button(text="➡️ Продолжить", callback_data="continue")
    builder.button(text="🗑 Удалить аккаунт", callback_data=f"delete:{index}")
    builder.adjust(1)
    return builder.as_markup()


@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет!\nОтправь мне файл <b>.session</b> или .zip с несколькими .session",
        parse_mode="HTML"
    )
    await state.set_state(SessionStates.waiting_session)


async def add_session_to_state(user_id: int, session_file_path: Path, state: FSMContext):
    data = await state.get_data() or {}
    accounts = data.get("accounts", [])
    accounts.append({
        "path": str(session_file_path),
        "name": session_file_path.name,
        "processed": False,
    })
    await state.update_data(accounts=accounts)


@dp.message(SessionStates.waiting_session, F.document)
async def receive_session(message: Message, state: FSMContext):
    document = message.document
    user_id = message.from_user.id

    if document.file_name.endswith('.session'):
        session_path = SESSIONS_DIR / f"{user_id}_{document.file_name}"
        await bot.download(document, destination=session_path)
        await add_session_to_state(user_id, session_path, state)
        data = await state.get_data()
        accounts = data.get("accounts", [])
        await message.answer(f"✅ Сессия сохранена: <code>{document.file_name}</code>", parse_mode="HTML")
        await message.answer("Выбери аккаунт:", reply_markup=build_accounts_keyboard(accounts))
        await state.set_state(None)
        return

    if document.file_name.endswith('.zip'):
        temp_dir = tempfile.mkdtemp()
        zip_path = Path(temp_dir) / document.file_name
        await bot.download(document, destination=zip_path)
        extracted = 0
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                for member in zf.namelist():
                    if member.endswith('.session'):
                        orig_name = Path(member).name
                        dest_path = SESSIONS_DIR / f"{user_id}_{orig_name}"
                        with zf.open(member) as src, open(dest_path, 'wb') as dst:
                            shutil.copyfileobj(src, dst)
                        await add_session_to_state(user_id, dest_path, state)
                        extracted += 1
        except Exception as e:
            await message.answer(f"❌ Ошибка при распаковке zip: <code>{e}</code>", parse_mode="HTML")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return
        shutil.rmtree(temp_dir, ignore_errors=True)
        if extracted == 0:
            await message.answer("В zip не найдено ни одного .session файла.")
            return
        data = await state.get_data()
        accounts = data.get("accounts", [])
        await message.answer(f"✅ Добавлено {extracted} сессий из архива.")
        await message.answer("Выбери аккаунт:", reply_markup=build_accounts_keyboard(accounts))
        await state.set_state(None)
        return

    await message.answer("Нужен файл .session или .zip с сессиями")


@dp.callback_query(F.data == "add_more")
async def add_more_handler(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Пришли ещё .session файл или .zip")
    await state.set_state(SessionStates.waiting_session)
    await callback.answer()


@dp.callback_query(F.data.startswith("select:"))
async def select_account_handler(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accounts = data.get("accounts", [])
    idx = int(callback.data.split(":", 1)[1])
    if idx < 0 or idx >= len(accounts):
        await callback.answer("Аккаунт не найден", show_alert=True)
        return
    acc = accounts[idx]
    await callback.message.edit_text(
        f"Аккаунт: <b>{acc.get('name')}</b>",
        parse_mode="HTML",
        reply_markup=build_account_menu(idx)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("getcode:"))
async def getcode_handler(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split(":", 1)[1])
    data = await state.get_data()
    accounts = data.get("accounts", [])

    if idx < 0 or idx >= len(accounts):
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    session_path = accounts[idx].get("path")
    if not session_path or not Path(session_path).exists():
        await callback.answer("Сессия не найдена", show_alert=True)
        return

    await callback.answer("Ищу код...")

    try:
        client = TelegramClient(session_path, API_ID, API_HASH)
        await client.connect()

        if not await client.is_user_authorized():
            await callback.message.answer("❌ Сессия не авторизована / протухла", reply_markup=build_account_menu(idx))
            await client.disconnect()
            return

        accounts[idx]["processed"] = True
        await state.update_data(accounts=accounts)

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
                reply_markup=build_account_menu(idx)
            )
        else:
            await callback.message.answer(
                "Код не найден. Запроси код заново и нажми кнопку.",
                reply_markup=build_account_menu(idx)
            )

    except SessionPasswordNeededError:
        await callback.message.answer(
            "На аккаунте стоит 2FA (облачный пароль).",
            reply_markup=build_account_menu(idx)
        )
    except Exception as e:
        await callback.message.answer(
            f"❌ Ошибка: <code>{e}</code>",
            parse_mode="HTML",
            reply_markup=build_account_menu(idx)
        )


@dp.callback_query(F.data == "continue")
async def continue_handler(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accounts = data.get("accounts", [])
    next_idx = None
    for i, acc in enumerate(accounts):
        if not acc.get("processed"):
            next_idx = i
            break
    if next_idx is None:
        await callback.message.edit_text("Все аккаунты обработаны.")
        await callback.answer()
        return
    acc = accounts[next_idx]
    await callback.message.edit_text(
        f"Аккаунт: <b>{acc.get('name')}</b>",
        parse_mode="HTML",
        reply_markup=build_account_menu(next_idx)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("delete:"))
async def delete_account_handler(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split(":", 1)[1])
    data = await state.get_data()
    accounts = data.get("accounts", [])

    if idx < 0 or idx >= len(accounts):
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    session_path = accounts[idx].get("path")
    if session_path and Path(session_path).exists():
        Path(session_path).unlink(missing_ok=True)

    accounts.pop(idx)
    await state.update_data(accounts=accounts)

    if accounts:
        await callback.message.edit_text("Аккаунт удалён. Выбери другой:", reply_markup=build_accounts_keyboard(accounts))
    else:
        await callback.message.edit_text("Аккаунт удалён. Пришлите новый .session или .zip")
        await state.set_state(SessionStates.waiting_session)
    await callback.answer()


@dp.callback_query(F.data == "delete_session")
async def delete_session_handler(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    accounts = data.get("accounts", [])

    for acc in accounts:
        p = acc.get("path")
        if p and Path(p).exists():
            Path(p).unlink(missing_ok=True)

    await state.clear()
    await callback.message.edit_text("Сессии удалены. Пришли новый .session или .zip")
    await state.set_state(SessionStates.waiting_session)
    await callback.answer()


async def main():
    print("Бот запущен (Telethon 1.28.5)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
