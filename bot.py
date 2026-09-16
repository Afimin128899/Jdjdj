import asyncio
import re
import shutil
import zipfile
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    AuthKeyUnregisteredError,
    AuthKeyDuplicatedError,
    UserDeactivatedError,
    UserDeactivatedBanError
)

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = "8468979285:AAGz8Zq3N1F01XjFWxTfDfWuOPHGRTAjEjY"
API_ID = 34910343
API_HASH = "d20860d195501ba0993b794f952b1ef1"

WORK_DIR = Path("session_checker")
WORK_DIR.mkdir(exist_ok=True)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class CheckStates(StatesGroup):
    waiting_sessions = State()

def get_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📦 Проверить пачку сессий", callback_data="start_check")
    builder.adjust(1)
    return builder.as_markup()

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🔍 <b>Проверка сессий</b>\n\n"
        "Отправь мне:\n"
        "• Архив <b>.zip</b> с .session файлами\n"
        "• Или несколько .session файлов подряд\n\n"
        "Я проверю до 100 штук и верну только <b>живые номера</b>.",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )

@dp.callback_query(F.data == "start_check")
async def start_check(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CheckStates.waiting_sessions)
    await state.update_data(files=[])
    
    await callback.message.edit_text(
        "Присылай сессии (архив .zip или файлы .session).\n"
        "Когда закончишь — напиши <b>/check</b>",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(CheckStates.waiting_sessions, F.document)
async def receive_file(message: Message, state: FSMContext):
    document = message.document
    data = await state.get_data()
    files = data.get("files", [])

    user_dir = WORK_DIR / str(message.from_user.id)
    user_dir.mkdir(exist_ok=True)

    file_path = user_dir / document.file_name
    await bot.download(document, destination=file_path)

    # Если это zip — распаковываем
    if document.file_name.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(user_dir)
            
            # Собираем все .session из архива
            for session_file in user_dir.rglob("*.session"):
                files.append(str(session_file))
            
            await message.answer(f"✅ Архив распакован. Найдено сессий: {len(list(user_dir.rglob('*.session')))}")
        except Exception as e:
            await message.answer(f"Ошибка распаковки: {e}")
            return
    else:
        if document.file_name.endswith(".session"):
            files.append(str(file_path))
            await message.answer(f"✅ Файл добавлен ({len(files)} шт.)")
        else:
            await message.answer("Нужен .session или .zip")
            return

    await state.update_data(files=files)

@dp.message(Command("check"))
async def run_check(message: Message, state: FSMContext):
    data = await state.get_data()
    files = data.get("files", [])

    if not files:
        await message.answer("Сначала пришли сессии.")
        return

    # Ограничиваем до 100
    files = files[:100]
    total = len(files)

    status_msg = await message.answer(f"⏳ Проверяю {total} сессий...")

    valid_numbers = []
    dead = 0
    errors = 0

    for i, session_path in enumerate(files, 1):
        try:
            client = TelegramClient(
                session_path,
                API_ID,
                API_HASH,
                device_model="Session Checker",
                system_version="1.0",
                app_version="1.0"
            )
            
            await client.connect()

            if await client.is_user_authorized():
                me = await client.get_me()
                phone = me.phone
                if phone:
                    if not phone.startswith("+"):
                        phone = "+" + phone
                    valid_numbers.append(phone)
            else:
                dead += 1

            await client.disconnect()

        except (AuthKeyUnregisteredError, AuthKeyDuplicatedError, 
                UserDeactivatedError, UserDeactivatedBanError):
            dead += 1
        except SessionPasswordNeededError:
            # Есть 2FA, но сессия живая — можно считать валидной
            try:
                me = await client.get_me()
                phone = me.phone
                if phone:
                    if not phone.startswith("+"):
                        phone = "+" + phone
                    valid_numbers.append(f"{phone} (2FA)")
            except:
                dead += 1
            finally:
                await client.disconnect()
        except Exception:
            errors += 1
            try:
                await client.disconnect()
            except:
                pass

        # Обновляем статус каждые 10 сессий
        if i % 10 == 0 or i == total:
            try:
                await status_msg.edit_text(
                    f"⏳ Проверено: {i}/{total}\n"
                    f"✅ Живых: {len(valid_numbers)}\n"
                    f"❌ Мёртвых: {dead}\n"
                    f"⚠️ Ошибок: {errors}"
                )
            except:
                pass

        await asyncio.sleep(0.3)  # небольшая пауза, чтобы не долбить

    # Формируем результат
    if valid_numbers:
        result_text = f"✅ <b>Живые номера ({len(valid_numbers)}):</b>\n\n"
        result_text += "\n".join(valid_numbers)
    else:
        result_text = "❌ Живых сессий не найдено."

    result_text += f"\n\n📊 Итого:\n• Всего проверено: {total}\n• Живых: {len(valid_numbers)}\n• Мёртвых: {dead}\n• Ошибок: {errors}"

    # Если много номеров — отправляем файлом
    if len(valid_numbers) > 30:
        result_file = WORK_DIR / f"valid_{message.from_user.id}.txt"
        result_file.write_text("\n".join(valid_numbers), encoding="utf-8")
        await message.answer_document(
            FSInputFile(result_file),
            caption=f"✅ Найдено живых: {len(valid_numbers)}"
        )
        result_file.unlink(missing_ok=True)
    else:
        await message.answer(result_text, parse_mode="HTML")

    # Чистим временные файлы
    user_dir = WORK_DIR / str(message.from_user.id)
    if user_dir.exists():
        shutil.rmtree(user_dir, ignore_errors=True)

    await state.clear()
    await message.answer("Проверка завершена.", reply_markup=get_main_keyboard())

@dp.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    user_dir = WORK_DIR / str(message.from_user.id)
    if user_dir.exists():
        shutil.rmtree(user_dir, ignore_errors=True)
    await message.answer("Отменено.", reply_markup=get_main_keyboard())

async def main():
    print("Бот проверки сессий запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
