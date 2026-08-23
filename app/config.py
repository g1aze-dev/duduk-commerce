import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Раньше здесь был дефолт "admin123" — если забыть задать ADMIN_PASSWORD
# в .env, админка тихо открывалась с всем известным паролем.
# Теперь при отсутствии пароля приложение не запустится вовсе.
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
if not ADMIN_PASSWORD:
    raise ValueError(
        "ADMIN_PASSWORD не задан в переменных окружения. "
        "Укажите его в .env (см. .env.example)."
    )

# Путь до страницы админки. /admin — первое, что перебирают автоматические
# сканеры и боты, поэтому путь лучше сделать непредсказуемым и держать
# в секрете (как ADMIN_PASSWORD), а не хардкодить в коде.
# Сам по себе секретный путь не заменяет пароль — это просто снижает
# количество автоматических попыток входа и шум в логах.
ADMIN_PATH = os.getenv("ADMIN_PATH", "admin").strip("/")

# Фото товаров храним в Cloudinary (бесплатный тариф), а не на диске Render —
# на free-плане Render нет persistent disk, и всё, что лежит рядом с кодом,
# стирается при каждом деплое / когда сервис "засыпает" и просыпается заново.
# CLOUDINARY_URL задаётся одной строкой вида:
#   cloudinary://<api_key>:<api_secret>@<cloud_name>
# Значение берётся из Dashboard на cloudinary.com (Account Details).
# Библиотека cloudinary сама читает эту переменную окружения при импорте —
# явно вызывать cloudinary.config() не нужно, если переменная задана.
CLOUDINARY_CONFIGURED = bool(os.getenv("CLOUDINARY_URL"))