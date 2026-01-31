from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import difflib

from app.database import get_db
from app import models
from pydantic import BaseModel

SYNONYMS = {
    "sheet": ["board", "ply"],
    "plywood": ["ply", "plywood sheet", "plywood board"],
}


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
# ADD ITEM FROM VOICE FLOW
# ------------------------
class ItemCreateFromVoice(BaseModel):
    name: str
    rate: float
    unit: str | None = None


@router.post("/add-from-voice", response_model=ItemResponse)
def add_item_from_voice(
    item: ItemCreateFromVoice,
    db: Session = Depends(get_db)
):
    normalized_name = item.name.lower().strip()

    existing = (
        db.query(models.ItemMaster)
        .filter(models.ItemMaster.name == normalized_name)
        .first()
    )
    if existing:
        return existing

    new_item = models.ItemMaster(
        name=normalized_name,
        rate=item.rate,
        unit=item.unit
    )

    db.add(new_item)
    db.commit()
    db.refresh(new_item)

    return new_item


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
# AI ITEM MATCHING HELPER
# ------------------------
class ItemResolveRequest(BaseModel):
    name: str


class ItemResolveResponse(BaseModel):
    matched: bool
    item_id: int | None
    name: str
    rate: float | None
    unit: str | None
    suggestions: list[dict]


@router.post("/resolve", response_model=ItemResolveResponse)
def resolve_item(request: ItemResolveRequest, db: Session = Depends(get_db)):
    query_name = request.name.lower().strip()

    # 1. Exact match
    exact_match = (
        db.query(models.ItemMaster)
        .filter(models.ItemMaster.name == query_name)
        .first()
    )
    if exact_match:
        return ItemResolveResponse(
            matched=True,
            item_id=exact_match.id,
            name=exact_match.name,
            rate=exact_match.rate,
            unit=exact_match.unit,
            suggestions=[]
        )

    # 2. Fuzzy + token-based suggestions
    all_items = db.query(models.ItemMaster).all()
    item_name_map = {item.name: item for item in all_items}

    query_tokens = query_name.split()

    candidate_names = set(item_name_map.keys())

    # Add synonym-expanded tokens
    expanded_tokens = set(query_tokens)
    for token in query_tokens:
        if token in SYNONYMS:
            expanded_tokens.update(SYNONYMS[token])

    # Token containment match
    token_matches = [
        name for name in candidate_names
        if any(tok in name for tok in expanded_tokens)
    ]

    # Difflib fallback
    close_names = difflib.get_close_matches(
        query_name,
        candidate_names,
        n=5,
        cutoff=0.5
    )

    final_matches = list(dict.fromkeys(token_matches + close_names))[:5]

    suggestions = [
        {
            "item_id": item_name_map[name].id,
            "name": item_name_map[name].name,
            "rate": item_name_map[name].rate,
            "unit": item_name_map[name].unit,
        }
        for name in final_matches
    ]

    return ItemResolveResponse(
        matched=False,
        item_id=None,
        name=request.name,
        rate=None,
        unit=None,
        suggestions=suggestions
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