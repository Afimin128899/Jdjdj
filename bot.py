import asyncio
import shutil
import zipfile
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

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

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🔍 <b>Проверка сессий</b>\n\n"
        "Просто отправь мне <b>.zip</b> архив с файлами <code>.session</code>\n"
        "Я проверю до 100 штук и верну только живые номера.",
        parse_mode="HTML"
    )

@dp.message(F.document)
async def handle_zip(message: Message):
    document = message.document

    if not document.file_name.lower().endswith(".zip"):
        await message.answer("Пришли именно <b>.zip</b> архив с сессиями", parse_mode="HTML")
        return

    user_id = message.from_user.id
    user_dir = WORK_DIR / str(user_id)

    # Чистим старую папку
    if user_dir.exists():
        shutil.rmtree(user_dir, ignore_errors=True)
    user_dir.mkdir(parents=True)

    # Скачиваем архив
    zip_path = user_dir / "sessions.zip"
    await bot.download(document, destination=zip_path)

    status = await message.answer("📦 Распаковываю архив...")

    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(user_dir)
    except Exception as e:
        await status.edit_text(f"❌ Не удалось распаковать архив:\n<code>{e}</code>", parse_mode="HTML")
        return

    # Собираем все .session
    session_files = list(user_dir.rglob("*.session"))
    session_files = session_files[:100]  # максимум 100

    if not session_files:
        await status.edit_text("❌ В архиве не найдено ни одного .session файла")
        return

    total = len(session_files)
    await status.edit_text(f"⏳ Найдено {total} сессий. Начинаю проверку...")

    valid_numbers = []
    dead = 0
    errors = 0

    for i, session_path in enumerate(session_files, 1):
        client = None
        try:
            client = TelegramClient(
                str(session_path),
                API_ID,
                API_HASH,
                device_model="SessionChecker",
                system_version="Windows 10",
                app_version="1.0"
            )
            await client.connect()

            if await client.is_user_authorized():
                me = await client.get_me()
                phone = me.phone
                if phone:
                    if not str(phone).startswith("+"):
                        phone = "+" + str(phone)
                    valid_numbers.append(phone)
            else:
                dead += 1

        except (AuthKeyUnregisteredError, AuthKeyDuplicatedError,
                UserDeactivatedError, UserDeactivatedBanError):
            dead += 1
        except SessionPasswordNeededError:
            # Сессия живая, но с 2FA
            try:
                me = await client.get_me()
                phone = me.phone
                if phone:
                    if not str(phone).startswith("+"):
                        phone = "+" + str(phone)
                    valid_numbers.append(f"{phone} (2FA)")
            except:
                dead += 1
        except Exception:
            errors += 1
        finally:
            if client:
                try:
                    await client.disconnect()
                except:
                    pass

        # Обновляем прогресс каждые 5–10 сессий
        if i % 8 == 0 or i == total:
            try:
                await status.edit_text(
                    f"⏳ Проверено: {i}/{total}\n"
                    f"✅ Живых: {len(valid_numbers)}\n"
                    f"❌ Мёртвых: {dead}\n"
                    f"⚠️ Ошибок: {errors}"
                )
            except:
                pass

        await asyncio.sleep(0.25)

    # ===== Результат =====
    if valid_numbers:
        text = f"✅ <b>Живые номера ({len(valid_numbers)}):</b>\n\n"
        text += "\n".join(valid_numbers)
        text += f"\n\n📊 Всего: {total} | Живых: {len(valid_numbers)} | Мёртвых: {dead} | Ошибок: {errors}"

        # Если номеров много — отправляем файлом
        if len(valid_numbers) > 40:
            result_file = user_dir / "valid_numbers.txt"
            result_file.write_text("\n".join(valid_numbers), encoding="utf-8")
            await message.answer_document(
                FSInputFile(result_file),
                caption=f"✅ Найдено живых номеров: <b>{len(valid_numbers)}</b>",
                parse_mode="HTML"
            )
        else:
            await message.answer(text, parse_mode="HTML")
    else:
        await message.answer(
            f"❌ Живых сессий не найдено.\n\n"
            f"Проверено: {total}\nМёртвых: {dead}\nОшибок: {errors}"
        )

    # Чистим за собой
    shutil.rmtree(user_dir, ignore_errors=True)

async def main():
    print("Бот проверки сессий запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
