from sqlalchemy.orm import Session
from sqlalchemy import or_

from app import models


def suggest_items(name: str, db: Session, limit: int = 5):
    """
    Suggest closest items from ItemMaster using partial token matching.
    Shared by Voice + Vision flows.
    """
    if not name:
        return []

    tokens = [t.lower() for t in name.split() if len(t) >= 3]
    if not tokens:
        return []

    conditions = [
        models.ItemMaster.name.ilike(f"%{token}%")
        for token in tokens
    ]

    results = (
        db.query(models.ItemMaster)
        .filter(or_(*conditions))
        .limit(limit)
        .all()
    )

    return [
        {
            "item_id": item.id,
            "name": item.name,
            "rate": item.rate,
            "unit": item.unit,
        }
        for item in results
    ]


def match_item_exact(name: str, db: Session):
    """
    Try to find a single exact / strong match from ItemMaster.
    Used by Vision → Item Matching step.
    """
    if not name:
        return None

    normalized = name.lower().strip()

    # 1️⃣ Exact case-insensitive match
    exact = (
        db.query(models.ItemMaster)
        .filter(models.ItemMaster.name.ilike(normalized))
        .first()
    )
    if exact:
        return {
            "item_id": exact.id,
            "name": exact.name,
            "rate": exact.rate,
            "unit": exact.unit,
        }

    # 2️⃣ Strong partial match (full name contained)
    partial = (
        db.query(models.ItemMaster)
        .filter(models.ItemMaster.name.ilike(f"%{normalized}%"))
        .first()
    )
    if partial:
        return {
            "item_id": partial.id,
            "name": partial.name,
            "rate": partial.rate,
            "unit": partial.unit,
        }

    return None
