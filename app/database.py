from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, update, delete, func, text
from .schemas import Base, Order, MenuItem, Category
import json
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import os

# На Vercel файловая система полностью read-only (кроме /tmp, который не
# сохраняется между вызовами функции) — файловый SQLite там в принципе
# не может писаться. На Render free-плане диск тоже эфемерный.
# Поэтому: если задан DATABASE_URL (например, Neon Postgres через Vercel
# Marketplace) — используем его. Если нет — работаем на локальном файле
# SQLite, как раньше (для разработки на своей машине).
_raw_url = (
    os.getenv("DATABASE_URL")
    or os.getenv("POSTGRES_URL")
    or os.getenv("POSTGRES_PRISMA_URL")
    or os.getenv("POSTGRES_URL_NON_POOLING")
)
connect_args = {}

if _raw_url:
    # Neon/Vercel отдают строку вида postgres://user:pass@host/db?sslmode=require —
    # для asyncpg нужен диалект postgresql+asyncpg://, а sslmode/channel_binding
    # в query string понимает libpq/psycopg, но не asyncpg — переносим SSL
    # в connect_args, а неподдерживаемые параметры просто выкидываем.
    if _raw_url.startswith("postgres://"):
        _raw_url = _raw_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif _raw_url.startswith("postgresql://") and "+asyncpg" not in _raw_url:
        _raw_url = _raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    parts = urlsplit(_raw_url)
    query = dict(parse_qsl(parts.query))
    sslmode = query.pop("sslmode", None)
    for _unsupported in ("channel_binding", "options"):
        query.pop(_unsupported, None)
    DATABASE_URL = urlunsplit(parts._replace(query=urlencode(query)))
    if sslmode and sslmode != "disable":
        connect_args = {"ssl": True}
else:
    _DATA_DIR = Path(os.getenv("DATA_DIR")) if os.getenv("DATA_DIR") else Path(__file__).resolve().parent.parent
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH = _DATA_DIR / "orders.db"
    DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

engine = create_async_engine(DATABASE_URL, echo=False, connect_args=connect_args)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

# created_at хранится в UTC (у Postgres — timestamp без TZ, считаем как UTC),
# а бизнес живёт в Перми — это тот же часовой пояс, что и Екатеринбург (UTC+5).
BUSINESS_TZ = ZoneInfo("Asia/Yekaterinburg")


def _local_day_bounds_utc() -> tuple[datetime, datetime]:
    """Границы текущих суток по местному времени, переведённые в UTC (naive)."""
    now_local = datetime.now(BUSINESS_TZ)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc


async def init_db():
    """Создаёт таблицы при запуске + миграции старых колонок"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Каждая миграция — в отдельной транзакции: на Postgres ошибка внутри
    # транзакции ("колонка уже есть") переводит её в aborted-состояние и
    # ломает любые следующие команды в том же блоке — в отличие от SQLite,
    # где это было безобидно.
    try:
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE menu_items ADD COLUMN image_url VARCHAR(500)"))
    except Exception:
        pass  # колонка уже существует

    try:
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE menu_items ADD COLUMN customizable BOOLEAN DEFAULT FALSE"))
            # Эта UPDATE выполнится только вместе с успешным ALTER выше
            # (то есть один раз, при первом добавлении колонки) — заполняет
            # разумные значения для уже существующих блюд, чтобы админу не
            # пришлось вручную включать настройку заново у всей шаурмы.
            await conn.execute(text(
                "UPDATE menu_items SET customizable = TRUE "
                "WHERE category IN ('shawarma', 'hot') "
                "AND lower(trim(name)) != 'картофель фри'"
            ))
    except Exception:
        pass  # колонка уже существует


async def save_order(order_data: dict) -> int:
    """Сохраняет заказ в БД"""
    async with AsyncSessionLocal() as session:
        order = Order(
            customer_name=order_data["customer_name"],
            phone=order_data["phone"],
            address=order_data["address"],
            items=json.dumps(order_data["items"]),
            total=order_data["total"],
            comment=order_data.get("comment")
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)
        return order.id

async def get_orders(status: Optional[str] = None) -> List[dict]:
    """Возвращает список заказов (все или по статусу)"""
    async with AsyncSessionLocal() as session:
        stmt = select(Order).order_by(Order.id.desc())
        if status:
            stmt = stmt.where(Order.status == status)
        result = await session.execute(stmt)
        orders = result.scalars().all()
        return [order.to_dict() for order in orders]

async def update_order_status(order_id: int, status: str):
    """Обновляет статус заказа"""
    async with AsyncSessionLocal() as session:
        stmt = update(Order).where(Order.id == order_id).values(status=status)
        await session.execute(stmt)
        await session.commit()

async def delete_order(order_id: int) -> bool:
    """Безвозвратно удаляет заказ из БД (в отличие от update_order_status
    со статусом 'cancelled', который лишь помечает заказ отменённым,
    оставляя запись в истории)."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if not order:
            return False
        await session.execute(delete(Order).where(Order.id == order_id))
        await session.commit()
        return True

async def get_stats() -> dict:
    """Возвращает статистику (сегодня, активные)"""
    start_utc, end_utc = _local_day_bounds_utc()

    async with AsyncSessionLocal() as session:
        # Сегодняшние заказы по местному времени (Пермь/Екатеринбург, UTC+5).
        # Количество считаем по всем заказам за сутки, а выручку — только
        # по не отменённым (отменённые раньше тоже попадали в сумму).
        result = await session.execute(
            text(
                "SELECT COUNT(*), COALESCE(SUM(CASE WHEN status != 'cancelled' THEN total ELSE 0 END), 0) "
                "FROM orders WHERE created_at >= :start_utc AND created_at < :end_utc"
            ),
            {"start_utc": start_utc, "end_utc": end_utc},
        )
        today_count, today_sum = result.one()

        # Активные заказы (status = 'new')
        result = await session.execute(
            select(func.count()).where(Order.status == 'new')
        )
        active = result.scalar()

        return {
            "today_orders": today_count or 0,
            "today_revenue": today_sum or 0,
            "active_orders": active or 0
        }

# ─── CATEGORIES ─────────────────────────────────────────────────────────────

DEFAULT_CATEGORIES = [
    {"name": "Шаурма",         "slug": "shawarma", "emoji": "🌯", "is_addon": False, "sort_order": 1},
    {"name": "Горячие блюда",  "slug": "hot",       "emoji": "🔥", "is_addon": False, "sort_order": 2},
    {"name": "Напитки",        "slug": "drinks",    "emoji": "☕", "is_addon": False, "sort_order": 3},
    {"name": "Детское меню",   "slug": "kids",      "emoji": "🍦", "is_addon": False, "sort_order": 4},
    {"name": "Добавки",        "slug": "dopings",   "emoji": "➕", "is_addon": True,  "sort_order": 5},
]

async def init_categories():
    """Заполняет таблицу категорий дефолтными значениями, если она пуста —
    чтобы у уже существующих блюд (с category='shawarma' и т.п.) сразу
    была соответствующая запись категории."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Category))
        if not result.scalars().first():
            for cat in DEFAULT_CATEGORIES:
                session.add(Category(**cat))
            await session.commit()

async def get_categories() -> List[dict]:
    async with AsyncSessionLocal() as session:
        stmt = select(Category).order_by(Category.sort_order, Category.id)
        result = await session.execute(stmt)
        return [c.to_dict() for c in result.scalars().all()]

async def create_category(data: dict) -> dict:
    async with AsyncSessionLocal() as session:
        cat = Category(**data)
        session.add(cat)
        await session.commit()
        await session.refresh(cat)
        return cat.to_dict()

async def update_category(cat_id: int, data: dict) -> Optional[dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Category).where(Category.id == cat_id))
        cat = result.scalar_one_or_none()
        if not cat:
            return None
        for k, v in data.items():
            setattr(cat, k, v)
        await session.commit()
        await session.refresh(cat)
        return cat.to_dict()

async def delete_category(cat_id: int) -> tuple[bool, str]:
    """Возвращает (успех, сообщение об ошибке, если не удалось)."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Category).where(Category.id == cat_id))
        cat = result.scalar_one_or_none()
        if not cat:
            return False, "Категория не найдена"
        # Не даём удалить категорию, если в ней ещё остались блюда — иначе
        # эти блюда молча потеряют категорию и выпадут из фильтров меню.
        count_result = await session.execute(
            select(func.count()).select_from(MenuItem).where(MenuItem.category == cat.slug)
        )
        items_count = count_result.scalar()
        if items_count > 0:
            return False, f"В категории ещё {items_count} блюд(о/а) — сначала перенесите или удалите их"
        await session.execute(delete(Category).where(Category.id == cat_id))
        await session.commit()
        return True, ""

# ─── MENU ───────────────────────────────────────────────────────────────────

DEFAULT_MENU = [
    # ── ШАУРМА ─────────────────────────────────────────────
    {"name": "Шаурма классическая",       "category": "shawarma", "price": 310, "desc": "Классическая шаурма с фирменным соусом",                            "emoji": "🌯", "badge": "Хит",        "customizable": True,  "sort_order": 1},
    {"name": "Шаурма с двойным мясом",    "category": "shawarma", "price": 350, "desc": "Двойная порция мяса — сытно и вкусно",                              "emoji": "🌯", "badge": "Большая",    "customizable": True,  "sort_order": 2},
    {"name": "Шаурма вегетарианская",     "category": "shawarma", "price": 230, "desc": "Свежие овощи, зелень, фирменный соус без мяса",                     "emoji": "🌯", "badge": "Вегет.",     "customizable": True,  "sort_order": 3},
    {"name": "Шаурма с курицей и беконом","category": "shawarma", "price": 340, "desc": "Курица, бекон, лист салата — нежно и сочно",                        "emoji": "🌯", "badge": None,         "customizable": True,  "sort_order": 4},
    {"name": "Шаурма МЕГА",               "category": "shawarma", "price": 410, "desc": "Максимальная шаурма для настоящего голода",                         "emoji": "🌯", "badge": "МЕГА",       "customizable": True,  "sort_order": 5},
    {"name": "Шаурма мини",               "category": "shawarma", "price": 230, "desc": "Маленькая шаурма — идеально для перекуса",                          "emoji": "🌯", "badge": None,         "customizable": True,  "sort_order": 6},
    {"name": "Шаурма ФИРМЕННАЯ ДУДУК",    "category": "shawarma", "price": 350, "desc": "Фирменный рецепт от шефа — попробуй обязательно",                   "emoji": "🌯", "badge": "Фирменная",  "customizable": True,  "sort_order": 7},
    # ── ШАВЕРМА ────────────────────────────────────────────
    {"name": "Шаверма классическая",      "category": "shawarma", "price": 300, "desc": "Классическая шаверма по петербургскому рецепту",                    "emoji": "🌮", "badge": None,         "customizable": True,  "sort_order": 8},
    {"name": "Шаверма с двойным мясом",   "category": "shawarma", "price": 350, "desc": "Двойная порция мяса в шаверме",                                     "emoji": "🌮", "badge": "Большая",    "customizable": True,  "sort_order": 9},
    {"name": "Шаверма вегетарианская",    "category": "shawarma", "price": 220, "desc": "Овощи, зелень, соус — без мяса",                                    "emoji": "🌮", "badge": "Вегет.",     "customizable": True,  "sort_order": 10},
    # ── ГОРЯЧИЕ БЛЮДА ──────────────────────────────────────
    {"name": "Плов",                       "category": "hot",      "price": 350, "desc": "Ароматный плов из баранины, цена за 100г",                          "emoji": "🍚", "badge": None,         "customizable": True,  "sort_order": 20},
    {"name": "Шашлык свинина",             "category": "hot",      "price": 200, "desc": "Сочный шашлык из свинины на углях, цена за 100г",                  "emoji": "🍖", "badge": None,         "customizable": True,  "sort_order": 21},
    {"name": "Шашлык курица",              "category": "hot",      "price": 180, "desc": "Нежный куриный шашлык на мангале, цена за 100г",                   "emoji": "🍗", "badge": None,         "customizable": True,  "sort_order": 22},
    {"name": "Люля-Кебаб свинина",         "category": "hot",      "price": 210, "desc": "Фарш свинины с луком и специями на шампуре, цена за 100г",         "emoji": "🍢", "badge": None,         "customizable": True,  "sort_order": 23},
    {"name": "Бртуч с люля-кебабом",       "category": "hot",      "price": 500, "desc": "Армянский лаваш с люля-кебабом, овощами и соусом, 1 шт.",          "emoji": "🫓", "badge": "Хит",        "customizable": True,  "sort_order": 24},
    {"name": "Бртуч армянский",            "category": "hot",      "price": 100, "desc": "Традиционный армянский лаваш, 1 шт.",                              "emoji": "🫓", "badge": None,         "customizable": True,  "sort_order": 25},
    {"name": "Картофель ФРИ",              "category": "hot",      "price": 160, "desc": "Хрустящий картофель фри, порция",                                  "emoji": "🍟", "badge": None,         "customizable": False, "sort_order": 26},
    # ── НАПИТКИ ────────────────────────────────────────────
    {"name": "Кофе Американо",             "category": "drinks",   "price": 90,  "desc": "Классический американо — бодрость с первого глотка",               "emoji": "☕", "badge": None,         "customizable": False, "sort_order": 30},
    {"name": "Капучино",                   "category": "drinks",   "price": 110, "desc": "Нежный капучино с молочной пенкой",                                "emoji": "☕", "badge": None,         "customizable": False, "sort_order": 31},
    {"name": "Молочный коктейль 300мл",    "category": "drinks",   "price": 190, "desc": "На выбор: клубника, банан, шоколад, карамель (+20₽ сироп)",        "emoji": "🥛", "badge": None,         "customizable": False, "sort_order": 32},
    # ── ДЕТСКОЕ МЕНЮ ───────────────────────────────────────
    {"name": "Мороженое Пломбир",          "category": "kids",     "price": 80,  "desc": "1 шарик классического пломбира",                                   "emoji": "🍦", "badge": None,         "customizable": False, "sort_order": 40},
    {"name": "Мороженое Ванильное",        "category": "kids",     "price": 50,  "desc": "1 шарик нежного ванильного мороженого",                            "emoji": "🍦", "badge": None,         "customizable": False, "sort_order": 41},
    {"name": "Мороженое Шоколадное",       "category": "kids",     "price": 50,  "desc": "1 шарик шоколадного мороженого",                                   "emoji": "🍫", "badge": None,         "customizable": False, "sort_order": 42},
    {"name": "Мороженое Клубничное",       "category": "kids",     "price": 50,  "desc": "1 шарик клубничного мороженого",                                   "emoji": "🍓", "badge": None,         "customizable": False, "sort_order": 43},
    # ── ДОБАВКИ (допинги) ───────────────────────────────────
    {"name": "Лук маринованный",           "category": "dopings",  "price": 15,  "desc": "30 гр.",                                                            "emoji": "🧅", "badge": None,         "customizable": False, "sort_order": 50},
    {"name": "Острый перчик халапеньо",    "category": "dopings",  "price": 20,  "desc": "10 гр.",                                                            "emoji": "🌶️", "badge": None,        "customizable": False, "sort_order": 51},
    {"name": "Капуста по-уральски",        "category": "dopings",  "price": 20,  "desc": "30 гр.",                                                            "emoji": "🥬", "badge": None,         "customizable": False, "sort_order": 52},
    {"name": "Дополнительный соус",        "category": "dopings",  "price": 25,  "desc": "50 гр.",                                                            "emoji": "🥫", "badge": None,         "customizable": False, "sort_order": 53},
    {"name": "Морковь по-корейски",        "category": "dopings",  "price": 25,  "desc": "20 гр.",                                                            "emoji": "🥕", "badge": None,         "customizable": False, "sort_order": 54},
    {"name": "Сыр плавленый",              "category": "dopings",  "price": 35,  "desc": "20 гр.",                                                            "emoji": "🧀", "badge": None,         "customizable": False, "sort_order": 55},
    {"name": "Бекон",                      "category": "dopings",  "price": 40,  "desc": "15 гр.",                                                            "emoji": "🥓", "badge": None,         "customizable": False, "sort_order": 56},
    {"name": "Жареное мясо",               "category": "dopings",  "price": 70,  "desc": "40 гр.",                                                            "emoji": "🥩", "badge": None,         "customizable": False, "sort_order": 57},
    {"name": "Лист салата",                "category": "dopings",  "price": 15,  "desc": "10 гр.",                                                            "emoji": "🥗", "badge": None,         "customizable": False, "sort_order": 58},
    {"name": "Картофель фри",              "category": "dopings",  "price": 25,  "desc": "30 гр.",                                                            "emoji": "🍟", "badge": None,         "customizable": False, "sort_order": 59},
    {"name": "Огурчик маринованный",       "category": "dopings",  "price": 15,  "desc": "20 гр.",                                                            "emoji": "🥒", "badge": None,         "customizable": False, "sort_order": 60},
    {"name": "Соус сырный",                "category": "dopings",  "price": 50,  "desc": "50 гр.",                                                            "emoji": "🧀", "badge": None,         "customizable": False, "sort_order": 61},
]

async def init_menu():
    """Заполняет меню дефолтными позициями если таблица пуста"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(MenuItem))
        if not result.scalars().first():
            for item in DEFAULT_MENU:
                session.add(MenuItem(**item))
            await session.commit()

async def get_menu(available_only: bool = False) -> List[dict]:
    async with AsyncSessionLocal() as session:
        stmt = select(MenuItem).order_by(MenuItem.sort_order, MenuItem.id)
        if available_only:
            stmt = stmt.where(MenuItem.available == True)
        result = await session.execute(stmt)
        return [m.to_dict() for m in result.scalars().all()]

async def get_menu_items_by_ids(ids: List[int]) -> dict:
    """Возвращает {id: dict} только для существующих и доступных позиций.
    Используется при оформлении заказа, чтобы брать актуальные name/price
    из БД, а не доверять тому, что прислал клиент."""
    if not ids:
        return {}
    async with AsyncSessionLocal() as session:
        stmt = select(MenuItem).where(MenuItem.id.in_(ids), MenuItem.available == True)
        result = await session.execute(stmt)
        return {m.id: m.to_dict() for m in result.scalars().all()}

async def create_menu_item(data: dict) -> dict:
    async with AsyncSessionLocal() as session:
        item = MenuItem(**data)
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return item.to_dict()

async def update_menu_item(item_id: int, data: dict) -> dict:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(MenuItem).where(MenuItem.id == item_id))
        item = result.scalar_one_or_none()
        if not item:
            return None
        for k, v in data.items():
            setattr(item, k, v)
        await session.commit()
        await session.refresh(item)
        return item.to_dict()

async def delete_menu_item(item_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(MenuItem).where(MenuItem.id == item_id))
        item = result.scalar_one_or_none()
        if not item:
            return False
        await session.delete(item)
        await session.commit()
        return True
