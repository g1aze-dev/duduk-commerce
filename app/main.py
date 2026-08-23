from fastapi import FastAPI, Request, UploadFile, File, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
from pathlib import Path
from .database import init_db, init_menu
from .routers import orders, admin, menu as menu_router
from .bot import init_bot
from .auth import verify_admin
from .config import ADMIN_PATH, CLOUDINARY_CONFIGURED
import cloudinary
import cloudinary.uploader
import io
import os

# Абсолютные пути от расположения файла, а не от текущей рабочей директории —
# раньше "static" и "app/templates" резолвились относительно cwd, из-за чего
# приложение могло не найти файлы при запуске не из корня проекта
# (например, из systemd-юнита или Docker с другим WORKDIR).
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "app" / "templates"

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await init_menu()
    await init_bot()
    yield

app = FastAPI(title="Шаурмечная", lifespan=lifespan)

# Фото товаров теперь хранятся не тут, а в Cloudinary (см. /api/upload-image) —
# на бесплатном плане Render локальный диск эфемерный и стирается при
# каждом деплое, так что "static/uploads" больше не нужен.
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

@app.middleware("http")
async def security_headers(request: Request, call_next):
    # Минимальный набор security-заголовков без новых зависимостей.
    # HSTS безопасен здесь, т.к. Render сам терминирует TLS и всегда
    # отдаёт сайт по https — браузер и так не увидит http-версию.
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response

@app.get("/health")
async def health():
    # Для health check в Render (и для ручной проверки, что процесс жив).
    return {"status": "ok"}

app.include_router(orders.router)
app.include_router(admin.router)
app.include_router(menu_router.router)

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get(f"/{ADMIN_PATH}", response_class=HTMLResponse)
async def admin_panel(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})

ALLOWED_UPLOAD_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

# Раньше загрузка не была ограничена по размеру — можно было залить
# сколько угодно данных под видом картинки. Читаем файл по чанкам и
# обрываем, как только превышен лимит, не давая накопить лишнее в памяти.
MAX_UPLOAD_SIZE = 8 * 1024 * 1024  # 8 МБ
UPLOAD_CHUNK_SIZE = 1024 * 1024

@app.post("/api/upload-image")
async def upload_image(file: UploadFile = File(...), _=Depends(verify_admin)):
    if not CLOUDINARY_CONFIGURED:
        return JSONResponse(
            status_code=500,
            content={"error": "Загрузка фото не настроена: не задана переменная окружения CLOUDINARY_URL."},
        )
    if file.content_type not in ALLOWED_UPLOAD_TYPES:
        return JSONResponse(status_code=400, content={"error": "Допустимы только изображения (jpg, png, webp, gif)"})

    buffer = io.BytesIO()
    total_size = 0
    while chunk := await file.read(UPLOAD_CHUNK_SIZE):
        total_size += len(chunk)
        if total_size > MAX_UPLOAD_SIZE:
            return JSONResponse(
                status_code=413,
                content={"error": f"Файл слишком большой (максимум {MAX_UPLOAD_SIZE // (1024*1024)} МБ)"},
            )
        buffer.write(chunk)
    buffer.seek(0)

    try:
        # folder группирует фото в отдельную папку в Cloudinary, unique_filename
        # даёт случайное имя — оригинальное имя файла от клиента ни на что не влияет.
        result = cloudinary.uploader.upload(
            buffer,
            folder="duduk/menu",
            unique_filename=True,
            overwrite=False,
            resource_type="image",
        )
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": f"Не удалось загрузить фото в облако: {e}"})

    return {"url": result["secure_url"]}
