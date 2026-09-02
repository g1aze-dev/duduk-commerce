from fastapi import APIRouter, HTTPException, Depends
from ..models import CategoryCreate, CategoryUpdate
from ..database import get_categories, create_category, update_category, delete_category
from ..auth import verify_admin

router = APIRouter(prefix="/api/categories", tags=["categories"])

# ── Public ──────────────────────────────────────────────
@router.get("")
async def public_categories():
    """Список категорий для витрины (фильтры) и админки."""
    return await get_categories()

# ── Admin ────────────────────────────────────────────────
@router.post("")
async def add_category(cat: CategoryCreate, _=Depends(verify_admin)):
    data = cat.model_dump()
    try:
        return await create_category(data)
    except Exception as e:
        # Скорее всего — конфликт уникальности slug
        raise HTTPException(status_code=400, detail=f"Не удалось создать категорию: возможно, такой slug уже занят ({e})")

@router.put("/{cat_id}")
async def edit_category(cat_id: int, cat: CategoryUpdate, _=Depends(verify_admin)):
    data = cat.model_dump()
    updated = await update_category(cat_id, data)
    if not updated:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    return updated

@router.delete("/{cat_id}")
async def remove_category(cat_id: int, _=Depends(verify_admin)):
    ok, msg = await delete_category(cat_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "ok"}
