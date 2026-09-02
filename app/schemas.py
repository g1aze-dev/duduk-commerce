from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, DateTime, func, Text
from datetime import datetime

class Base(AsyncAttrs, DeclarativeBase):
    pass

class Order(Base):
    __tablename__ = "orders"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    customer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    address: Mapped[str] = mapped_column(String(200), nullable=False)
    items: Mapped[str] = mapped_column(Text, nullable=False)  # JSON строка
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="new")
    comment: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    
    def to_dict(self):
        return {
            "id": self.id,
            "customer_name": self.customer_name,
            "phone": self.phone,
            "address": self.address,
            "items": self.items,
            "total": self.total,
            "status": self.status,
            "comment": self.comment,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class MenuItem(Base):
    __tablename__ = "menu_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="shawarma")
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    desc: Mapped[str] = mapped_column(Text, nullable=True)
    emoji: Mapped[str] = mapped_column(String(10), nullable=True, default="🌯")
    image_url: Mapped[str] = mapped_column(String(500), nullable=True, default=None)
    badge: Mapped[str] = mapped_column(String(50), nullable=True)
    available: Mapped[bool] = mapped_column(default=True)
    # Раньше "можно ли настроить блюдо" вычислялось на фронте по категории
    # (жёстко: шаурма/горячее — да, остальное — нет, плюс отдельное
    # исключение для картофеля фри). Теперь это явный флаг, который
    # задаёт админ для каждого блюда отдельно — гибче и без правок кода.
    customizable: Mapped[bool] = mapped_column(default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "price": self.price,
            "desc": self.desc or "",
            "emoji": self.emoji or "🌯",
            "image_url": self.image_url or None,
            "badge": self.badge,
            "available": self.available,
            "customizable": self.customizable,
            "sort_order": self.sort_order,
        }

class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # slug — то, что раньше было хардкодным значением в MenuItem.category
    # ("shawarma", "hot", ...). Уникален, используется для связи с блюдами.
    slug: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    icon_url: Mapped[str] = mapped_column(String(500), nullable=True, default=None)
    emoji: Mapped[str] = mapped_column(String(10), nullable=True, default="🌯")
    # Категории вроде "Добавки" — не самостоятельный раздел меню, а список
    # допов для конструктора/оформления заказа. Раньше это было зашито
    # в код как строка "dopings"; теперь это флаг, который можно поставить
    # любой новой категории такого же назначения.
    is_addon: Mapped[bool] = mapped_column(default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "icon_url": self.icon_url,
            "emoji": self.emoji or "🌯",
            "is_addon": self.is_addon,
            "sort_order": self.sort_order,
        }
