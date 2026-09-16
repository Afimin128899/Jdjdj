import asyncio
import shutil
import zipfile
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile
from aiogram.filters import CommandStart

from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    AuthKeyUnregisteredError,
    AuthKeyDuplicatedError,
    UserDeactivatedError,
    UserDeactivatedBanError,
    AuthKeyError
)

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = "8468979285:AAGz8Zq3N1F01XjFWxTfDfWuOPHGRTAjEjY"
API_ID = 34910343
API_HASH = "d20860d195501ba0993b794f952b1ef1"

WORK_DIR = Path("session_checker")
WORK_DIR.mkdir(exist_ok=True)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "🔍 <b>Проверка сессий</b>\n\n"
        "Отправь <b>.zip</b> с файлами <code>.session</code>\n"
        "Я верну архив только с <b>живыми</b> сессиями.",
        parse_mode="HTML"
    )

@dp.message(F.document)
async def handle_zip(message: Message):
    document = message.document

    if not document.file_name.lower().endswith(".zip"):
        await message.answer("Нужен файл <b>.zip</b>", parse_mode="HTML")
        return

    user_id = message.from_user.id
    user_dir = WORK_DIR / str(user_id)
    valid_dir = user_dir / "valid"

    # Чистим
    if user_dir.exists():
        shutil.rmtree(user_dir, ignore_errors=True)
    user_dir.mkdir(parents=True)
    valid_dir.mkdir()

    zip_path = user_dir / "input.zip"
    status = await message.answer("📥 Скачиваю архив...")

    try:
        await bot.download(document, destination=zip_path)
    except Exception as e:
        await status.edit_text(f"❌ Ошибка скачивания: {e}")
        return

    await status.edit_text("📦 Распаковываю...")

    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(user_dir)
    except Exception as e:
        await status.edit_text(f"❌ Ошибка распаковки: {e}")
        return

    session_files = list(user_dir.rglob("*.session"))
    session_files = [f for f in session_files if f.is_file()][:100]

    if not session_files:
        await status.edit_text("❌ В архиве нет .session файлов")
        return

    total = len(session_files)
    await status.edit_text(f"🔍 Найдено {total} сессий. Проверяю...")

    valid_count = 0
    dead = 0
    errors = 0
    valid_phones = []

    for idx, session_path in enumerate(session_files, 1):
        client = None
        is_valid = False
        phone = None

        try:
            client = TelegramClient(
                session=str(session_path),
                api_id=API_ID,
                api_hash=API_HASH,
                device_model="Desktop",
                system_version="Windows 10",
                app_version="4.2.4"
            )

            await asyncio.wait_for(client.connect(), timeout=12)

            if await client.is_user_authorized():
                me = await client.get_me()
                phone = getattr(me, "phone", None)
                if phone:
                    phone = str(phone)
                    if not phone.startswith("+"):
                        phone = "+" + phone
                    is_valid = True
            else:
                dead += 1

        except (AuthKeyUnregisteredError, AuthKeyDuplicatedError,
                UserDeactivatedError, UserDeactivatedBanError, AuthKeyError):
            dead += 1
        except SessionPasswordNeededError:
            # Считаем живой (есть 2FA)
            try:
                me = await client.get_me()
                phone = getattr(me, "phone", None)
                if phone:
                    phone = str(phone)
                    if not phone.startswith("+"):
                        phone = "+" + phone
                    is_valid = True
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

        # Если сессия живая — копируем её в папку valid
        if is_valid and phone:
            valid_count += 1
            valid_phones.append(phone)

            # Имя файла = номер телефона
            new_name = f"{phone}.session"
            dest = valid_dir / new_name
            try:
                shutil.copy2(session_path, dest)
            except:
                # Если не получилось по номеру — оставляем оригинальное имя
                shutil.copy2(session_path, valid_dir / session_path.name)

        if idx % 6 == 0 or idx == total:
            try:
                await status.edit_text(
                    f"⏳ {idx}/{total}\n"
                    f"✅ Живых: {valid_count}\n"
                    f"❌ Мёртвых: {dead}\n"
                    f"⚠️ Ошибок: {errors}"
                )
            except:
                pass

        await asyncio.sleep(0.15)

    # ===== Создаём архив с живыми сессиями =====
    if valid_count > 0:
        output_zip = user_dir / "valid_sessions.zip"
        
        with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file in valid_dir.glob("*.session"):
                zf.write(file, arcname=file.name)

        caption = (
            f"✅ <b>Готово!</b>\n\n"
            f"Живых сессий: <b>{valid_count}</b>\n"
            f"Мёртвых: {dead}\n"
            f"Ошибок: {errors}"
        )

        await message.answer_document(
            FSInputFile(output_zip),
            caption=caption,
            parse_mode="HTML"
        )
    else:
        await message.answer(
            f"❌ Живых сессий не найдено\n\n"
            f"Проверено: {total}\n"
            f"Мёртвых: {dead}\n"
            f"Ошибок: {errors}"
        )

    # Очистка
    shutil.rmtree(user_dir, ignore_errors=True)

async def main():
    print("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
