import asyncio
import shutil
import zipfile
import traceback
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
        "Отправь мне <b>.zip</b> архив с файлами <code>.session</code>\n"
        "Я проверю их и верну только живые номера.",
        parse_mode="HTML"
    )

@dp.message(F.document)
async def handle_zip(message: Message):
    document = message.document

    if not document.file_name.lower().endswith(".zip"):
        await message.answer("Нужен именно файл <b>.zip</b>", parse_mode="HTML")
        return

    user_id = message.from_user.id
    user_dir = WORK_DIR / str(user_id)

    # Полностью чистим папку пользователя
    if user_dir.exists():
        shutil.rmtree(user_dir, ignore_errors=True)
    user_dir.mkdir(parents=True, exist_ok=True)

    zip_path = user_dir / "archive.zip"
    
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
        await status.edit_text(f"❌ Не удалось распаковать архив:\n<code>{e}</code>", parse_mode="HTML")
        return

    # Ищем все .session файлы (даже во вложенных папках)
    session_files = list(user_dir.rglob("*.session"))
    session_files = [f for f in session_files if f.is_file()][:100]

    if not session_files:
        await status.edit_text("❌ В архиве нет ни одного файла .session")
        return

    total = len(session_files)
    await status.edit_text(f"🔍 Найдено {total} сессий. Начинаю проверку...")

    valid = []
    dead = 0
    errors = 0

    for idx, session_path in enumerate(session_files, 1):
        client = None
        try:
            client = TelegramClient(
                session=str(session_path),
                api_id=API_ID,
                api_hash=API_HASH,
                device_model="Desktop",
                system_version="Windows 10",
                app_version="4.2.4",
                lang_code="en",
                system_lang_code="en"
            )

            await asyncio.wait_for(client.connect(), timeout=15)

            if not await client.is_user_authorized():
                dead += 1
            else:
                me = await client.get_me()
                phone = getattr(me, "phone", None)
                if phone:
                    phone = str(phone)
                    if not phone.startswith("+"):
                        phone = "+" + phone
                    valid.append(phone)
                else:
                    dead += 1

        except (AuthKeyUnregisteredError, AuthKeyDuplicatedError, 
                UserDeactivatedError, UserDeactivatedBanError, AuthKeyError):
            dead += 1
        except SessionPasswordNeededError:
            # Сессия живая + 2FA
            try:
                me = await client.get_me()
                phone = getattr(me, "phone", None)
                if phone:
                    phone = str(phone)
                    if not phone.startswith("+"):
                        phone = "+" + phone
                    valid.append(f"{phone} (2FA)")
                else:
                    dead += 1
            except:
                dead += 1
        except Exception as e:
            errors += 1
            # Раскомментируй следующую строку, если хочешь видеть ошибки в консоли
            # print(f"Ошибка на {session_path.name}: {e}")
        finally:
            if client:
                try:
                    await client.disconnect()
                except:
                    pass

        # Обновляем статус
        if idx % 7 == 0 or idx == total:
            try:
                await status.edit_text(
                    f"⏳ Прогресс: {idx}/{total}\n"
                    f"✅ Живых: {len(valid)}\n"
                    f"❌ Мёртвых: {dead}\n"
                    f"⚠️ Ошибок: {errors}"
                )
            except:
                pass

        await asyncio.sleep(0.2)

    # ===== Результат =====
    result_text = (
        f"📊 <b>Результат проверки</b>\n\n"
        f"Всего сессий: <b>{total}</b>\n"
        f"Живых: <b>{len(valid)}</b>\n"
        f"Мёртвых: <b>{dead}</b>\n"
        f"Ошибок: <b>{errors}</b>\n\n"
    )

    if valid:
        result_text += "<b>Живые номера:</b>\n" + "\n".join(valid)

        if len(valid) > 35:
            # Отправляем файлом
            txt_path = user_dir / "valid_numbers.txt"
            txt_path.write_text("\n".join(valid), encoding="utf-8")
            await message.answer_document(
                FSInputFile(txt_path),
                caption=f"✅ Живых номеров: <b>{len(valid)}</b>",
                parse_mode="HTML"
            )
        else:
            await message.answer(result_text, parse_mode="HTML")
    else:
        await message.answer(result_text + "Живых сессий не найдено.", parse_mode="HTML")

    # Очистка
    try:
        shutil.rmtree(user_dir, ignore_errors=True)
    except:
        pass

async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
