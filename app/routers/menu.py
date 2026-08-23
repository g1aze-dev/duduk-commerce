from fastapi import APIRouter, HTTPException, Depends
from ..models import MenuItemCreate, MenuItemUpdate
from ..database import get_menu, create_menu_item, update_menu_item, delete_menu_item
from ..auth import verify_admin

router = APIRouter(prefix="/api/menu", tags=["menu"])

# ── Public ──────────────────────────────────────────────
@router.get("")
async def public_menu():
    """Возвращает только доступные позиции меню (для клиента)"""
    return await get_menu(available_only=True)

# ── Admin ────────────────────────────────────────────────
@router.get("/all")
async def admin_menu(_=Depends(verify_admin)):
    """Все позиции (включая скрытые), для админки"""
    return await get_menu(available_only=False)

@router.post("")
async def add_item(item: MenuItemCreate, _=Depends(verify_admin)):
    data = item.model_dump()
    created = await create_menu_item(data)
    return created

@router.put("/{item_id}")
async def edit_item(item_id: int, item: MenuItemUpdate, _=Depends(verify_admin)):
    data = item.model_dump()
    updated = await update_menu_item(item_id, data)
    if not updated:
        raise HTTPException(status_code=404, detail="Позиция не найдена")
    return updated

@router.delete("/{item_id}")
async def remove_item(item_id: int, _=Depends(verify_admin)):
    ok = await delete_menu_item(item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Позиция не найдена")
    return {"status": "ok"}
