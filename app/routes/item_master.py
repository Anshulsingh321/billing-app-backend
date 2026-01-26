from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app import models
from pydantic import BaseModel


router = APIRouter(
    prefix="/items",
    tags=["Item Master"]
)


# ------------------------
# SCHEMAS (local)
# ------------------------
class ItemCreate(BaseModel):
    name: str
    rate: float
    unit: str | None = None


class ItemResponse(BaseModel):
    id: int
    name: str
    rate: float
    unit: str | None

    class Config:
        from_attributes = True


# ------------------------
# CREATE ITEM
# ------------------------
@router.post("/", response_model=ItemResponse)
def create_item(item: ItemCreate, db: Session = Depends(get_db)):
    existing = (
        db.query(models.ItemMaster)
        .filter(models.ItemMaster.name.ilike(item.name))
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Item already exists")

    new_item = models.ItemMaster(
        name=item.name.lower(),
        rate=item.rate,
        unit=item.unit
    )
    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    return new_item


# ------------------------
# LIST ALL ITEMS
# ------------------------
@router.get("/", response_model=List[ItemResponse])
def list_items(db: Session = Depends(get_db)):
    return db.query(models.ItemMaster).order_by(models.ItemMaster.name).all()


# ------------------------
# SEARCH ITEMS
# ------------------------
@router.get("/search", response_model=List[ItemResponse])
def search_items(q: str, db: Session = Depends(get_db)):
    return (
        db.query(models.ItemMaster)
        .filter(models.ItemMaster.name.ilike(f"%{q.lower()}%"))
        .order_by(models.ItemMaster.name)
        .all()
    )


# ------------------------
# UPDATE ITEM RATE / UNIT
# ------------------------
@router.put("/{item_id}", response_model=ItemResponse)
def update_item(
    item_id: int,
    item: ItemCreate,
    db: Session = Depends(get_db)
):
    db_item = (
        db.query(models.ItemMaster)
        .filter(models.ItemMaster.id == item_id)
        .first()
    )
    if not db_item:
        raise HTTPException(status_code=404, detail="Item not found")

    db_item.name = item.name.lower()
    db_item.rate = item.rate
    db_item.unit = item.unit

    db.commit()
    db.refresh(db_item)
    return db_item