import time
import json
from fastapi import APIRouter, HTTPException, Depends, Request

from ..models import OrderCreate
from ..database import save_order, get_orders, update_order_status, get_menu_items_by_ids
from ..bot import send_order_notification
from ..auth import verify_admin

router = APIRouter(prefix="/api", tags=["orders"])

# ── Простой rate-limit на создание заказов, чтобы бота/БД нельзя было
#    завалить потоком фейковых заказов. Не заменяет полноценный WAF,
#    но закрывает самый очевидный кейс.
ORDER_RATE_LIMIT = 5          # заказов
ORDER_RATE_WINDOW = 60        # за это окно, секунд
_order_timestamps: dict[str, list[float]] = {}

# Минимальная сумма заказа для доставки. Проверяется на сервере (а не
# только в интерфейсе), чтобы это нельзя было обойти прямым запросом к API.
MIN_ORDER_TOTAL = 400


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(ip: str):
    now = time.time()
    timestamps = [t for t in _order_timestamps.get(ip, []) if now - t < ORDER_RATE_WINDOW]
    if len(timestamps) >= ORDER_RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Слишком много заказов подряд. Попробуйте через минуту.",
        )
    timestamps.append(now)
    _order_timestamps[ip] = timestamps


# ── Public: оформление заказа ─────────────────────────────
@router.post("/order")
async def create_order(order: OrderCreate, request: Request):
    _check_rate_limit(_client_ip(request))

    # ── Пересчёт состава и суммы заказа на сервере ────────
    # Раньше name/price/total принимались от клиента как есть, из-за чего
    # можно было отправить заказ с произвольной (например, заниженной)
    # ценой. Теперь берём только item_id + quantity, а актуальные name/price
    # тянем из БД. Заодно это закрывает и XSS: имя позиции больше не может
    # быть произвольной строкой от клиента — только то, что реально есть
    # в меню и что задал админ.
    requested_ids = [i.item_id for i in order.items]
    menu_map = await get_menu_items_by_ids(requested_ids)

    unknown_ids = [i for i in requested_ids if i not in menu_map]
    if unknown_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Некоторые позиции недоступны или не найдены: {unknown_ids}",
        )

    items_list = []
    total = 0
    for order_item in order.items:
        menu_item = menu_map[order_item.item_id]
        line_total = menu_item["price"] * order_item.quantity
        total += line_total
        items_list.append({
            "name": menu_item["name"],
            "price": menu_item["price"],
            "quantity": order_item.quantity,
        })

    # Минимальная сумма заказа — считаем ПОСЛЕ пересчёта total на сервере,
    # а не по тому, что прислал клиент, иначе порог можно обойти.
    if total < MIN_ORDER_TOTAL:
        raise HTTPException(
            status_code=400,
            detail=f"Минимальная сумма заказа — {MIN_ORDER_TOTAL} ₽. Ваша сумма: {total} ₽.",
        )

    order_id = await save_order({
        "customer_name": order.customer_name,
        "phone": order.phone,
        "address": order.address,
        "items": items_list,
        "total": total,
        "comment": order.comment
    })

    order_data = {
        "id": order_id,
        "customer_name": order.customer_name,
        "phone": order.phone,
        "address": order.address,
        "items": json.dumps(items_list),
        "total": total,
        "comment": order.comment,
        "created_at": "только что"
    }

    await send_order_notification(order_data)

    return {"status": "ok", "order_id": order_id, "total": total}


# ── Admin only: просмотр и изменение чужих заказов ────────
# Раньше эти эндпоинты были без авторизации — любой мог прочитать
# имена/телефоны/адреса всех клиентов и менять статус заказов.
@router.get("/orders")
async def get_all_orders(_=Depends(verify_admin)):
    return await get_orders()


@router.get("/orders/new")
async def get_new_orders(_=Depends(verify_admin)):
    return await get_orders(status="new")


@router.get("/order/{order_id}")
async def get_order_by_id(order_id: int, _=Depends(verify_admin)):
    orders = await get_orders()
    for order in orders:
        if order["id"] == order_id:
            return order
    raise HTTPException(status_code=404, detail="Заказ не найден")


@router.put("/order/{order_id}/status")
async def change_status(order_id: int, status: str, _=Depends(verify_admin)):
    if status not in ["new", "done", "cancelled"]:
        raise HTTPException(status_code=400, detail="Неверный статус")
    await update_order_status(order_id, status)
    return {"status": "ok"}