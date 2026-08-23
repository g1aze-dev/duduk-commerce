from fastapi import APIRouter, Depends
from ..database import get_orders, update_order_status, get_stats, _local_day_bounds_utc
from ..auth import verify_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])

@router.get("/stats")
async def stats(_=Depends(verify_admin)):
    base = await get_stats()
    all_orders = await get_orders()
    start_utc, end_utc = _local_day_bounds_utc()
    start_str, end_str = str(start_utc), str(end_utc)
    today_done = sum(
        1 for o in all_orders
        if o.get("status") == "done"
        and start_str <= str(o.get("created_at", "")) < end_str
    )
    return {**base, "done_orders": today_done}

@router.get("/orders")
async def all_orders(_=Depends(verify_admin)):
    return await get_orders()

@router.put("/order/{order_id}/complete")
async def complete_order(order_id: int, _=Depends(verify_admin)):
    await update_order_status(order_id, "done")
    return {"status": "ok"}

@router.delete("/order/{order_id}")
async def cancel_order(order_id: int, _=Depends(verify_admin)):
    await update_order_status(order_id, "cancelled")
    return {"status": "ok"}