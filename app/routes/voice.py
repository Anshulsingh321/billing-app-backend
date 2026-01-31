import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

from google import genai
from google.genai.types import GenerateContentConfig
import json
import re

from app.utils.item_matcher import suggest_items

from sqlalchemy.orm import Session
from fastapi import Depends
from app.database import get_db
from app import models
from app.utils.json_utils import extract_json


# ------------------------------------------------------------------
# ENV
# ------------------------------------------------------------------
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY not found in environment")

# ------------------------------------------------------------------
# GEMINI CLIENT (NEW API – CORRECT)
# ------------------------------------------------------------------
client = genai.Client(api_key=GEMINI_API_KEY)

MODEL_NAME = "gemini-3-flash-preview"
print("✅ Gemini Voice model loaded:", MODEL_NAME)

# ------------------------------------------------------------------
# FASTAPI
# ------------------------------------------------------------------
router = APIRouter(prefix="/parse-voice", tags=["Voice AI"])


class VoiceInput(BaseModel):
    text: str


def safe_json_loads(raw_text: str):
    """
    Safely extracts and parses JSON from Gemini responses.
    Handles markdown fences and extra text.
    """
    if not raw_text:
        raise ValueError("Empty response from Gemini")

    # Remove markdown code fences if present
    cleaned = re.sub(r"```json|```", "", raw_text, flags=re.IGNORECASE).strip()

    # Find first JSON object
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in Gemini response: {raw_text}")

    return json.loads(match.group())


def resolve_item(name: str, db: Session):
    # Try exact-ish match first
    item = (
        db.query(models.ItemMaster)
        .filter(models.ItemMaster.name.ilike(name))
        .first()
    )
    if item:
        return {
            "matched": True,
            "item_id": item.id,
            "name": item.name,
            "rate": item.rate,
            "unit": item.unit,
            "suggestions": []
        }

    # Otherwise suggest close matches
    suggestions = suggest_items(name, db)

    return {
        "matched": False,
        "item_id": None,
        "name": name,
        "rate": None,
        "unit": None,
        "suggestions": suggestions
    }




# ------------------------------------------------------------------
# TEST ENDPOINT (VERY IMPORTANT)
# ------------------------------------------------------------------
@router.get("/test")
def test_gemini():
    """
    Simple health check to confirm Gemini is working.
    """
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents="Reply with exactly: OK",
        )

        return {
            "status": "success",
            "gemini_reply": response.text.strip(),
            "model": MODEL_NAME,
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Gemini error: {str(e)}"
        )


# ------------------------------------------------------------------
# VOICE PARSING ENDPOINT
# ------------------------------------------------------------------
@router.post("/")
def parse_voice(payload: VoiceInput, db: Session = Depends(get_db)):
    """
    Converts spoken text into structured billing intent.
    GUARANTEES valid JSON output.
    """

    system_prompt = """
You are a billing assistant.

Return ONLY valid JSON.
Do NOT add markdown.
Do NOT explain.
Do NOT add extra text.

JSON format:
{
  "customer_name": string | null,
  "items": [
    {
      "name": string,
      "quantity": number | null,
      "price": number | null
    }
  ]
}
"""

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=[
                system_prompt,
                f'Spoken input: "{payload.text}"'
            ],
            config=GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=512,
                response_mime_type="application/json",
            ),
        )

        raw_text = response.text

        try:
            parsed = extract_json(raw_text)
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"Invalid JSON from Gemini: {str(e)}"
            )

        ready_items = []
        unmatched_items = []

        for item in parsed.get("items", []):
            result = resolve_item(item["name"], db)
            if result["matched"]:
                ready_items.append({
                    **result,
                    "quantity": item.get("quantity")
                })
            else:
                unmatched_items.append({
                    "name": item["name"],
                    "quantity": item.get("quantity"),
                    "suggestions": result.get("suggestions", [])
                })

        return {
            "customer_name": parsed.get("customer_name"),
            "ready_items": ready_items,
            "unmatched_items": unmatched_items,
            "next_action": "CONFIRM_ITEMS" if unmatched_items else "CREATE_BILL",
            "model": MODEL_NAME
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Gemini error: {str(e)}"
        )

# ------------------------------------------------------------------
# CREATE BILL FROM VOICE (STEP 3) - REFACTORED
# ------------------------------------------------------------------
class CreateBillFromVoice(BaseModel):
    customer_name: str
    bill_type: str = "NON_GST"
    items: list  # [{ item_id, quantity }]


class VoiceCorrectionInput(BaseModel):
    bill_id: int
    command: str

# ------------------------------------------------------------------
# FINALIZE BILL FROM VOICE INPUT MODEL
# ------------------------------------------------------------------
class FinalizeBillFromVoiceInput(BaseModel):
    bill_id: int

@router.post("/create-bill")
def create_bill_from_voice(
    payload: CreateBillFromVoice,
    db: Session = Depends(get_db)
):
    # 1️⃣ Find or create customer
    customer = (
        db.query(models.Customer)
        .filter(models.Customer.name.ilike(payload.customer_name))
        .first()
    )

    if not customer:
        customer = models.Customer(name=payload.customer_name)
        db.add(customer)
        db.commit()
        db.refresh(customer)

    # 2️⃣ Resolve bill type safely
    bill_type_map = {
        "NON_GST": models.BillType.NON_GST,
        "GST": models.BillType.GST,
        "UDHAR": models.BillType.UDHAR,
    }
    bill_type = bill_type_map.get(
        (payload.bill_type or "NON_GST").upper(),
        models.BillType.NON_GST,
    )

    # 3️⃣ Create OPEN bill
    bill = models.Bill(
        customer_id=customer.id,
        bill_type=bill_type,
        status=models.BillStatus.OPEN,
    )
    db.add(bill)
    db.commit()
    db.refresh(bill)

    total = 0.0

    # 4️⃣ Add items
    for item in payload.items:
        item_master = db.get(models.ItemMaster, item["item_id"])
        if not item_master:
            continue

        quantity = float(item.get("quantity", 1))
        rate = float(item_master.rate)
        subtotal = quantity * rate
        total += subtotal

        bill_item = models.BillItem(
            bill_id=bill.id,
            item_name=item_master.name,
            quantity=quantity,
            rate=rate,
            unit=item_master.unit,
            subtotal=subtotal,
        )
        db.add(bill_item)

    # 5️⃣ Auto-calculate totals (DO NOT FINALIZE HERE)
    bill.subtotal = round(total, 2)

    gst_amount = 0.0
    if bill.bill_type == models.BillType.GST:
        gst_amount = round(bill.subtotal * 0.18, 2)

    bill.gst_amount = gst_amount
    bill.total_amount = round(bill.subtotal + gst_amount, 2)

    # Keep bill OPEN for corrections
    bill.status = models.BillStatus.OPEN

    db.commit()
    db.refresh(bill)

    return {
        "message": "Bill created from voice (OPEN for correction)",
        "bill_id": bill.id,
        "customer": customer.name,
        "bill_type": bill.bill_type,
        "status": bill.status,
        "subtotal": bill.subtotal,
        "gst_amount": bill.gst_amount,
        "total_amount": bill.total_amount,
        "next_action": "VOICE_CORRECTION_OR_FINALIZE",
    }

@router.post("/correct-bill")
def correct_bill_from_voice(
    payload: VoiceCorrectionInput,
    db: Session = Depends(get_db)
):
    bill = db.query(models.Bill).filter(
        models.Bill.id == payload.bill_id,
        models.Bill.status == models.BillStatus.OPEN
    ).first()

    if not bill:
        raise HTTPException(status_code=400, detail="Editable OPEN bill not found")

    bill_items = (
        db.query(models.BillItem)
        .filter(models.BillItem.bill_id == bill.id)
        .all()
    )

    if not bill_items:
        raise HTTPException(status_code=400, detail="No items in bill to modify")

    command = payload.command.lower().strip()

    action = None
    target_name = None
    value = None

    # CHANGE QUANTITY
    match = re.search(r"(change|set)\s+(.*?)\s+quantity\s+to\s+(\d+)", command)
    if match:
        action = "UPDATE_QUANTITY"
        target_name = match.group(2).strip()
        value = float(match.group(3))

    # CHANGE RATE
    match = re.search(r"(change|set)\s+(.*?)\s+rate\s+to\s+(\d+)", command)
    if match:
        action = "UPDATE_RATE"
        target_name = match.group(2).strip()
        value = float(match.group(3))

    # REMOVE ITEM
    match = re.search(r"(remove|delete)\s+(.*)", command)
    if match:
        action = "REMOVE"
        target_name = match.group(2).strip()

    if not action or not target_name:
        raise HTTPException(
            status_code=422,
            detail="Could not understand correction command. Please rephrase."
        )

    changes = []

    for item in bill_items:
        if target_name in item.item_name.lower():
            if action == "UPDATE_QUANTITY" and value is not None:
                old_qty = item.quantity
                item.quantity = value
                item.subtotal = item.quantity * item.rate
                changes.append(
                    f"Updated {item.item_name} quantity {old_qty} → {item.quantity}"
                )

            elif action == "UPDATE_RATE" and value is not None:
                old_rate = item.rate
                item.rate = value
                item.subtotal = item.quantity * item.rate
                changes.append(
                    f"Updated {item.item_name} rate {old_rate} → {item.rate}"
                )

            elif action == "REMOVE":
                db.delete(item)
                changes.append(f"Removed {item.item_name}")

    if not changes:
        raise HTTPException(
            status_code=404,
            detail="Item mentioned in command not found in bill"
        )

    db.flush()

    remaining_items = (
        db.query(models.BillItem)
        .filter(models.BillItem.bill_id == bill.id)
        .all()
    )

    subtotal = sum(item.subtotal for item in remaining_items)

    gst_amount = 0.0
    if bill.bill_type == models.BillType.GST:
        gst_amount = round(subtotal * 0.18, 2)

    bill.subtotal = round(subtotal, 2)
    bill.gst_amount = gst_amount
    bill.total_amount = round(subtotal + gst_amount, 2)

    db.commit()
    db.refresh(bill)

    return {
        "message": "Bill updated via voice",
        "changes": changes,
        "bill_id": bill.id,
        "new_total": bill.total_amount,
        "next_action": "VOICE_CORRECTION_OR_FINALIZE"
    }
# ------------------------------------------------------------------
# CONFIRM ITEMS FROM VOICE (STEP 3A)
# ------------------------------------------------------------------

class ConfirmItemsInput(BaseModel):
    customer_name: str
    items: list  # [{ item_id: int, quantity: float }]


@router.post("/confirm-items")
def confirm_items_from_voice(
    payload: ConfirmItemsInput,
    db: Session = Depends(get_db)
):
    confirmed_items = []

    for item in payload.items:
        item_master = db.get(models.ItemMaster, item["item_id"])
        if not item_master:
            raise HTTPException(
                status_code=400,
                detail=f"Item ID {item['item_id']} not found in item master"
            )

        confirmed_items.append({
            "item_id": item_master.id,
            "name": item_master.name,
            "rate": item_master.rate,
            "unit": item_master.unit,
            "quantity": item.get("quantity", 1),
        })

    if not confirmed_items:
        raise HTTPException(
            status_code=400,
            detail="No items confirmed"
        )

    return {
        "status": "CONFIRMED",
        "customer_name": payload.customer_name,
        "items": confirmed_items,
        "next_action": "CREATE_BILL"
    }

# ------------------------------------------------------------------
# FINALIZE BILL FROM VOICE ENDPOINT
# ------------------------------------------------------------------
@router.post("/finalize-bill")
def finalize_bill_from_voice(
    payload: FinalizeBillFromVoiceInput,
    db: Session = Depends(get_db)
):
    bill = db.query(models.Bill).filter(
        models.Bill.id == payload.bill_id,
        models.Bill.status == models.BillStatus.OPEN
    ).first()

    if not bill:
        raise HTTPException(
            status_code=400,
            detail="Editable OPEN bill not found"
        )

    items = (
        db.query(models.BillItem)
        .filter(models.BillItem.bill_id == bill.id)
        .all()
    )

    if not items:
        raise HTTPException(
            status_code=400,
            detail="Cannot finalize empty bill"
        )

    subtotal = sum(item.subtotal for item in items)

    gst_amount = 0.0
    if bill.bill_type == models.BillType.GST:
        gst_amount = round(subtotal * 0.18, 2)

    bill.subtotal = round(subtotal, 2)
    bill.gst_amount = gst_amount
    bill.total_amount = round(subtotal + gst_amount, 2)
    bill.status = models.BillStatus.FINALIZED

    db.commit()
    db.refresh(bill)

    return {
        "message": "Bill finalized via voice",
        "bill_id": bill.id,
        "status": bill.status,
        "subtotal": bill.subtotal,
        "gst_amount": bill.gst_amount,
        "total_amount": bill.total_amount,
        "next_action": "PAY_OR_SHARE_PDF"
    }

# ------------------------------------------------------------------
# VOICE PAYMENT INPUT MODEL
# ------------------------------------------------------------------
class VoicePaymentInput(BaseModel):
    bill_id: int
    amount: float
    method: str | None = "cash"

# ------------------------------------------------------------------
# PAY BILL VIA VOICE ENDPOINT
# ------------------------------------------------------------------
@router.post("/pay-bill")
def pay_bill_via_voice(
    payload: VoicePaymentInput,
    db: Session = Depends(get_db)
):
    bill = db.query(models.Bill).filter(models.Bill.id == payload.bill_id).first()

    if not bill or bill.status != models.BillStatus.FINALIZED:
        raise HTTPException(
            status_code=400,
            detail="Bill not found or not in FINALIZED status"
        )

    payment = models.Payment(
        bill_id=bill.id,
        amount=payload.amount,
        method=payload.method or "cash"
    )
    db.add(payment)

    if bill.paid_amount is None:
        bill.paid_amount = 0.0
    bill.paid_amount += payload.amount

    if bill.paid_amount >= bill.total_amount:
        bill.status = models.BillStatus.PAID
    else:
        bill.status = models.BillStatus.FINALIZED

    db.commit()
    db.refresh(bill)

    remaining_amount = max(bill.total_amount - bill.paid_amount, 0.0)

    return {
        "bill_id": bill.id,
        "status": bill.status,
        "paid_amount": bill.paid_amount,
        "remaining_amount": remaining_amount,
        "message": "Payment recorded via voice"
    }