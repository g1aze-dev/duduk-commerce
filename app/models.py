from pydantic import BaseModel, constr, field_validator
from typing import List, Optional
from datetime import datetime

class OrderItem(BaseModel):
    # Клиент присылает ТОЛЬКО ссылку на позицию меню и количество.
    # Имя и цена больше не принимаются от клиента — раньше их можно было
    # подделать (заказать что угодно за 1₽); сервер сам подставляет
    # актуальные name/price из БД по item_id (см. routers/orders.py).
    item_id: int
    quantity: int

    @field_validator('quantity')
    def validate_quantity(cls, v):
        if v <= 0 or v > 50:
            raise ValueError('Количество должно быть от 1 до 50')
        return v

class OrderCreate(BaseModel):
    customer_name: constr(min_length=1, max_length=100)
    phone: constr(min_length=10, max_length=20)
    address: constr(min_length=1, max_length=200)
    items: List[OrderItem]
    comment: Optional[str] = None
    # total больше не принимается от клиента — считается сервером
    # по актуальным ценам из меню.

    @field_validator('items')
    def validate_items(cls, v):
        if not v:
            raise ValueError('Заказ не может быть пустым')
        if len(v) > 100:
            raise ValueError('Слишком много позиций в заказе')
        return v

    @field_validator('phone')
    def validate_phone(cls, v):
        # Простая валидация телефона
        import re
        if not re.match(r'^\+?[0-9]{10,15}$', v):
            raise ValueError('Неверный формат телефона')
        return v

class OrderResponse(BaseModel):
    id: int
    customer_name: str
    phone: str
    address: str
    items: str
    total: int
    status: str
    comment: Optional[str] = None
    created_at: datetime

class MenuItemCreate(BaseModel):
    name: str
    category: str
    price: int
    desc: Optional[str] = ""
    emoji: Optional[str] = "🌯"
    image_url: Optional[str] = None
    badge: Optional[str] = None
    available: Optional[bool] = True
    # Можно ли настроить блюдо (добавки/ингредиенты) — задаётся явно
    # админом для каждой позиции, а не выводится из категории.
    customizable: Optional[bool] = False

class MenuItemUpdate(MenuItemCreate):
    pass

class CategoryCreate(BaseModel):
    name: constr(min_length=1, max_length=100)
    slug: constr(min_length=1, max_length=50)
    icon_url: Optional[str] = None
    emoji: Optional[str] = "🌯"
    is_addon: Optional[bool] = False
    sort_order: Optional[int] = 0

    @field_validator('slug')
    def validate_slug(cls, v):
        import re
        v = v.strip().lower()
        if not re.match(r'^[a-z0-9_-]+$', v):
            raise ValueError('Слаг может содержать только латинские буквы (a-z), цифры, - и _')
        return v

class CategoryUpdate(CategoryCreate):
    pass
