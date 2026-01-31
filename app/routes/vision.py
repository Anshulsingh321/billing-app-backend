from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from google.cloud import vision
import json
import tempfile
import os
import io
from typing import List
from sqlalchemy.orm import Session
from app.database import get_db
from app import models
from app.utils.item_matcher import match_item_exact, suggest_items

# Gemini imports
from google import genai
from google.genai.types import GenerateContentConfig
from app.schemas import VisionTextNormalizeRequest

router = APIRouter(prefix="/vision", tags=["Vision"])
@router.post("/health")
def vision_health():
    return {"status": "Vision route working"}
# Initialize Google Vision client (Railway-safe)
# Supports GOOGLE_APPLICATION_CREDENTIALS_JSON (recommended for cloud)
init_error = None
vision_client = None

try:
    credentials_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if credentials_json:
        temp_cred_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        temp_cred_file.write(credentials_json.encode("utf-8"))
        temp_cred_file.flush()
        temp_cred_file.close()
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp_cred_file.name

    vision_client = vision.ImageAnnotatorClient()

except Exception as e:
    init_error = str(e)
    vision_client = None

# Initialize Gemini client
GEMINI_MODEL = "gemini-3-flash-preview"
try:
    gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
except Exception as e:
    gemini_client = None
    gemini_init_error = str(e)

# Known brand keywords (rule-based, deterministic)
BRAND_KEYWORDS = {
    "fevicol": "Fevicol",
    "pidilite": "Pidilite",
    "asian paints": "Asian Paints",
    "berger": "Berger",
    "nerolac": "Nerolac",
}

def detect_brand(lines: list[str]) -> str | None:
    for line in lines:
        lower_line = line.lower()
        for key, brand in BRAND_KEYWORDS.items():
            if key in lower_line:
                return brand
    return None


@router.post("/detect")
async def detect_objects_and_labels(image: UploadFile = File(...)):
    """
    STEP 1: Pure Vision detection.
    - Input: image file
    - Output: labels + objects
    - No DB, no billing, no Gemini
    """
    if vision_client is None:
        raise HTTPException(
            status_code=500,
            detail=f"Vision client not initialized: {init_error}"
        )

    if not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Invalid image file")

    content = await image.read()
    vision_image = vision.Image(content=content)

    try:
        label_response = vision_client.label_detection(image=vision_image)
        object_response = vision_client.object_localization(image=vision_image)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vision API error: {str(e)}")

    labels = [
        {
            "name": label.description,
            "confidence": round(label.score, 2)
        }
        for label in label_response.label_annotations
    ]

    objects = [
        {
            "name": obj.name,
            "confidence": round(obj.score, 2)
        }
        for obj in object_response.localized_object_annotations
    ]

    return {
        "labels": labels,
        "objects": objects
    }


# STEP 2: TEXT detection using Google Vision OCR
@router.post("/detect-text")
async def detect_text(image: UploadFile = File(...)):
    """
    STEP 2: TEXT detection using Google Vision OCR.
    - Input: image file
    - Output: detected text blocks
    """
    if vision_client is None:
        raise HTTPException(
            status_code=500,
            detail=f"Vision client not initialized: {init_error}"
        )

    if not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Invalid image file")

    content = await image.read()
    vision_image = vision.Image(content=content)

    try:
        text_response = vision_client.text_detection(image=vision_image)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vision API error: {str(e)}")

    texts = text_response.text_annotations

    if not texts:
        return {"detected_text": []}

    # First annotation contains full text, rest are individual blocks
    full_text = texts[0].description.strip()

    lines = [
        line.strip()
        for line in full_text.splitlines()
        if line.strip()
    ]

    return {
        "full_text": full_text,
        "lines": lines
    }


# Endpoint: Normalize OCR text with Gemini
@router.post("/normalize-text")
def normalize_ocr_text(payload: VisionTextNormalizeRequest):
    if gemini_client is None:
        raise HTTPException(
            status_code=500,
            detail=f"Gemini client not initialized: {gemini_init_error}"
        )

    lines = payload.lines
    brand = detect_brand(lines)

    text = "\n".join(lines)

    prompt = (
        "You are a product classification assistant.\n\n"
        "Rules:\n"
        "- Ignore brand names completely.\n"
        "- Identify ONLY the generic product type.\n"
        "- Use 2–4 words.\n"
        "- No marketing text.\n"
        "- Capitalize properly.\n"
        "- Return ONLY the product type.\n\n"
        "Extracted text:\n"
        f"{text}\n\n"
        "Product type:"
    )

    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[prompt],
            config=GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=64
            ),
        )
        product_type = response.text.strip()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini error: {str(e)}")

    if brand:
        final_name = f"{brand} {product_type}"
    else:
        final_name = product_type

    return {
        "brand": brand,
        "product_type": product_type,
        "normalized_product": final_name,
        "model": GEMINI_MODEL
    }

# STEP 3: Resolve normalized product into billing-ready structure
@router.post("/resolve-product")
def resolve_product_for_billing(payload: dict, db: Session = Depends(get_db)):
    """
    STEP 3: Bridge Vision → Billing
    Input:
    {
      "normalized_product": string,
      "quantity": number (optional, default 1)
    }

    Output mirrors voice flow structure so UI & billing stay unified.
    """
    name = payload.get("normalized_product")
    if not name:
        raise HTTPException(status_code=400, detail="normalized_product is required")

    quantity = payload.get("quantity", 1)

    matched_item = match_item_exact(name, db)
    if matched_item:
        ready_items = [{
            "item_id": matched_item.id,
            "name": matched_item.name,
            "rate": matched_item.rate,
            "unit": matched_item.unit,
            "quantity": quantity
        }]
        unmatched_items = []
    else:
        ready_items = []
        suggestions = suggest_items(name, db)
        unmatched_items = [{
            "name": name,
            "quantity": quantity,
            "suggestions": suggestions
        }]

    return {
        "customer_name": None,
        "ready_items": ready_items,
        "unmatched_items": unmatched_items,
        "next_action": "CONFIRM_ITEMS",
        "source": "VISION"
    }