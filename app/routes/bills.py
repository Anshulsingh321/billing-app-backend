from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime

# --- Invoice numbering helpers ---
def generate_invoice_number(db):
    year = datetime.utcnow().year

    last_bill = (
        db.query(models.Bill)
        .filter(models.Bill.invoice_number.isnot(None))
        .order_by(models.Bill.id.desc())
        .first()
    )

    if not last_bill or not last_bill.invoice_number:
        return f"INV-{year}-0001"

    last_number = int(last_bill.invoice_number.split("-")[-1])
    return f"INV-{year}-{last_number + 1:04d}"


def generate_gst_invoice_number(db):
    year = datetime.utcnow().year

    last_bill = (
        db.query(models.Bill)
        .filter(models.Bill.gst_invoice_number.isnot(None))
        .order_by(models.Bill.id.desc())
        .first()
    )

    if not last_bill or not last_bill.gst_invoice_number:
        return f"GST-{year}-0001"

    last_number = int(last_bill.gst_invoice_number.split("-")[-1])
    return f"GST-{year}-{last_number + 1:04d}"

from app import models, schemas
from app.pdf_utils import generate_bill_pdf
from app.database import get_db

GST_RATE = 0.18

class BillAdjustmentCreate(schemas.BaseModel):
    amount: float
    reason: str | None = None

router = APIRouter(
    prefix="/bills",
    tags=["Bills"]
)

# -------------------------
# CREATE BILL
# -------------------------
@router.post("/")
def create_bill(
    bill: schemas.BillCreate,
    db: Session = Depends(get_db)
):
    gst_rate = 18 if bill.bill_type == models.BillType.GST else 0

    new_bill = models.Bill(
        customer_id=bill.customer_id,
        bill_type=bill.bill_type,
        gst_rate=gst_rate
    )
    db.add(new_bill)
    db.commit()
    db.refresh(new_bill)

    return {
        "id": new_bill.id,
        "customer_id": new_bill.customer_id,
        "bill_type": new_bill.bill_type
    }


# -------------------------
# ADD ITEM TO BILL
# -------------------------
@router.post("/{bill_id}/items")
def add_bill_item(
    bill_id: int,
    item: schemas.BillItemCreate,
    db: Session = Depends(get_db)
):
    bill = db.query(models.Bill).filter(models.Bill.id == bill_id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")

    # 🔒 Allow adding items only if bill is OPEN
    if bill.status != models.BillStatus.OPEN:
        raise HTTPException(
            status_code=400,
            detail="Bill is finalized and cannot be modified"
        )

    # 🔍 Look for item in ItemMaster
    master = (
        db.query(models.ItemMaster)
        .filter(models.ItemMaster.name.ilike(item.item_name))
        .first()
    )

    # ❌ Item not found & rate missing
    if not master and item.rate is None:
        raise HTTPException(
            status_code=400,
            detail="RATE_MISSING"
        )

    # ✅ If item exists → use stored rate
    if master:
        rate = master.rate
        unit = master.unit

    # ✅ If item does NOT exist → save it
    else:
        rate = item.rate
        unit = item.unit

        new_master = models.ItemMaster(
            name=item.item_name.lower(),
            rate=rate,
            unit=unit
        )
        db.add(new_master)
        db.commit()

    subtotal = round(item.quantity * rate, 2)

    bill_item = models.BillItem(
        bill_id=bill_id,
        item_name=item.item_name.lower(),
        quantity=item.quantity,
        rate=rate,
        unit=unit,
        subtotal=subtotal
    )

    db.add(bill_item)
    db.commit()
    db.refresh(bill_item)

    # Recompute bill totals from DB items (GST not applied per item)
    bill.subtotal = sum(i.subtotal for i in bill.items)
    bill.gst_amount = 0
    bill.total_amount = bill.subtotal

    db.commit()
    db.refresh(bill)

    return {
        "id": bill_item.id,
        "item_name": bill_item.item_name,
        "quantity": bill_item.quantity,
        "rate": bill_item.rate,
        "unit": bill_item.unit,
        "subtotal": bill_item.subtotal
    }


# -------------------------
# FINALIZE BILL
# -------------------------
@router.post("/{bill_id}/finalize")
def finalize_bill(
    bill_id: int,
    db: Session = Depends(get_db)
):
    bill = db.query(models.Bill).filter(models.Bill.id == bill_id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")

    # 🔒 Bill already finalized
    if bill.status == models.BillStatus.FINALIZED:
        raise HTTPException(
            status_code=400,
            detail="Bill is already finalized"
        )

    items = (
        db.query(models.BillItem)
        .filter(models.BillItem.bill_id == bill_id)
        .all()
    )

    if not items:
        raise HTTPException(
            status_code=400,
            detail="Cannot finalize empty bill"
        )

    subtotal = sum(item.subtotal for item in items)

    gst_amount = 0
    if bill.bill_type == models.BillType.GST:
        gst_amount = round(subtotal * bill.gst_rate / 100, 2)

    total_amount = round(subtotal + gst_amount, 2)

    bill.subtotal = subtotal
    bill.gst_amount = gst_amount
    bill.total_amount = total_amount

    # ✅ Generate invoice numbers ONLY on finalize
    bill.invoice_number = generate_invoice_number(db)

    if bill.bill_type == models.BillType.GST:
        bill.gst_invoice_number = generate_gst_invoice_number(db)
        bill.gst_invoice_date = datetime.utcnow()

    bill.status = models.BillStatus.FINALIZED

    db.commit()
    db.refresh(bill)

    return {
        "bill_id": bill.id,
        "status": bill.status,
        "subtotal": subtotal,
        "gst": gst_amount,
        "total_amount": bill.total_amount,
        "message": "Bill finalized successfully"
    }

# -------------------------
# PAY BILL
# -------------------------
@router.post("/{bill_id}/pay")
def pay_bill(
    bill_id: int,
    payment: schemas.BillPaymentCreate,
    db: Session = Depends(get_db)
):
    bill = db.query(models.Bill).filter(models.Bill.id == bill_id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")

    # ❌ Cannot pay an OPEN bill
    if bill.status == models.BillStatus.OPEN:
        raise HTTPException(
            status_code=400,
            detail="Finalize bill before accepting payment"
        )

    # ❌ No overpayment allowed
    if bill.paid_amount + payment.amount > bill.total_amount:
        raise HTTPException(
            status_code=400,
            detail="Payment exceeds bill total"
        )

    bill.paid_amount += payment.amount

    # ✅ Update bill status
    if bill.paid_amount == bill.total_amount:
        bill.status = models.BillStatus.PAID
    else:
        bill.status = models.BillStatus.PARTIALLY_PAID

    db.commit()
    db.refresh(bill)

    return {
        "bill_id": bill.id,
        "status": bill.status,
        "paid_amount": bill.paid_amount,
        "total_amount": bill.total_amount,
        "remaining": round(bill.total_amount - bill.paid_amount, 2)
    }

# -------------------------
# ADJUST / RETURN ITEMS
# -------------------------
@router.post("/{bill_id}/adjust")
def adjust_bill(
    bill_id: int,
    adj: BillAdjustmentCreate,
    db: Session = Depends(get_db)
):
    bill = db.query(models.Bill).filter(models.Bill.id == bill_id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")

    # ❌ Only finalized or paid bills can be adjusted
    if bill.status == models.BillStatus.OPEN:
        raise HTTPException(
            status_code=400,
            detail="Cannot adjust an open bill"
        )

    if adj.amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="Adjustment amount must be positive"
        )

    if adj.amount > bill.total_amount:
        raise HTTPException(
            status_code=400,
            detail="Adjustment exceeds bill total"
        )

    adjustment = models.BillAdjustment(
        bill_id=bill.id,
        amount=adj.amount,
        reason=adj.reason,
        created_at=datetime.utcnow()
    )

    # Apply adjustment
    bill.total_amount -= adj.amount

    # If already paid more than new total → cap paid amount
    if bill.paid_amount > bill.total_amount:
        bill.paid_amount = bill.total_amount

    # Update status
    if bill.paid_amount == bill.total_amount:
        bill.status = models.BillStatus.PAID
    elif bill.paid_amount == 0:
        bill.status = models.BillStatus.FINALIZED
    else:
        bill.status = models.BillStatus.PARTIALLY_PAID

    db.add(adjustment)
    db.commit()
    db.refresh(bill)

    return {
        "bill_id": bill.id,
        "adjusted_amount": adj.amount,
        "new_total": bill.total_amount,
        "paid_amount": bill.paid_amount,
        "remaining": round(bill.total_amount - bill.paid_amount, 2),
        "status": bill.status,
        "message": "Bill adjusted successfully"
    }

# -------------------------
# VIEW BILL PDF (INLINE)
# -------------------------
@router.get("/{bill_id}/pdf")
def view_bill_pdf(
    bill_id: int,
    db: Session = Depends(get_db)
):
    bill = db.query(models.Bill).filter(models.Bill.id == bill_id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    if bill.status != models.BillStatus.FINALIZED:
        raise HTTPException(
            status_code=400,
            detail="Bill must be finalized before viewing PDF"
        )

    customer = db.query(models.Customer).filter(
        models.Customer.id == bill.customer_id
    ).first()

    items = (
        db.query(models.BillItem)
        .filter(models.BillItem.bill_id == bill_id)
        .all()
    )

    if not items:
        print("⚠️ WARNING: No items found for bill", bill_id)

    # Use stored values from bill (do not recalculate GST)
    subtotal = bill.subtotal
    gst_amount = bill.gst_amount
    grand_total = bill.total_amount

    pdf_path = generate_bill_pdf(
        bill=bill,
        customer=customer,
        items=items,
        subtotal=subtotal,
        gst_amount=gst_amount,
        grand_total=grand_total
    )

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=bill_{bill_id}.pdf"
        }
    )


# -------------------------
# DOWNLOAD BILL PDF
# -------------------------
@router.get("/{bill_id}/pdf/download")
def download_bill_pdf(
    bill_id: int,
    db: Session = Depends(get_db)
):
    bill = db.query(models.Bill).filter(models.Bill.id == bill_id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    if bill.status != models.BillStatus.FINALIZED:
        raise HTTPException(
            status_code=400,
            detail="Bill must be finalized before downloading PDF"
        )

    customer = db.query(models.Customer).filter(
        models.Customer.id == bill.customer_id
    ).first()

    items = (
        db.query(models.BillItem)
        .filter(models.BillItem.bill_id == bill_id)
        .all()
    )

    # Use stored values from bill (do not recalculate GST)
    subtotal = bill.subtotal
    gst_amount = bill.gst_amount
    grand_total = bill.total_amount

    pdf_path = generate_bill_pdf(
        bill=bill,
        customer=customer,
        items=items,
        subtotal=subtotal,
        gst_amount=gst_amount,
        grand_total=grand_total
    )

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=f"bill_{bill_id}.pdf"
    )

# -------------------------
# LIST BILLS (HISTORY)
# -------------------------
@router.get("/")
def list_bills(
    customer_id: int | None = None,
    bill_type: models.BillType | None = None,
    status: models.BillStatus | None = None,
    from_date: str | None = None,  # YYYY-MM-DD
    to_date: str | None = None,    # YYYY-MM-DD
    db: Session = Depends(get_db)
):
    q = db.query(models.Bill)

    if customer_id is not None:
        q = q.filter(models.Bill.customer_id == customer_id)

    if bill_type is not None:
        q = q.filter(models.Bill.bill_type == bill_type)

    if status is not None:
        q = q.filter(models.Bill.status == status)

    if from_date is not None:
        q = q.filter(func.date(models.Bill.created_at) >= from_date)

    if to_date is not None:
        q = q.filter(func.date(models.Bill.created_at) <= to_date)

    bills = q.order_by(models.Bill.created_at.desc()).all()

    return [
        {
            "bill_id": b.id,
            "customer_id": b.customer_id,
            "bill_type": b.bill_type,
            "status": b.status,
            "total_amount": b.total_amount,
            "paid_amount": b.paid_amount,
            "created_at": b.created_at,
        }
        for b in bills
    ]

# -------------------------
# DAILY SUMMARY
# -------------------------
@router.get("/summary/daily")
def daily_summary(
    date: str | None = None,  # YYYY-MM-DD, defaults to today
    db: Session = Depends(get_db)
):
    q = db.query(models.Bill)

    # Default = today
    if date is None:
        q = q.filter(func.date(models.Bill.created_at) == func.current_date())
    else:
        q = q.filter(func.date(models.Bill.created_at) == date)

    bills = q.all()

    total_sales = sum(b.total_amount for b in bills)
    total_received = sum(b.paid_amount for b in bills)

    udhar_added = sum(
        (b.total_amount - b.paid_amount)
        for b in bills
        if b.bill_type == models.BillType.UDHAR
    )

    return {
        "date": date or "today",
        "total_bills": len(bills),
        "total_sales": total_sales,
        "cash_received": total_received,
        "udhar_added": udhar_added,
    }

# -------------------------
# DATE RANGE SUMMARY
# -------------------------
@router.get("/summary/range")
def range_summary(
    from_date: str,
    to_date: str,
    db: Session = Depends(get_db)
):
    bills = (
        db.query(models.Bill)
        .filter(func.date(models.Bill.created_at) >= from_date)
        .filter(func.date(models.Bill.created_at) <= to_date)
        .all()
    )

    total_sales = sum(b.total_amount for b in bills)
    total_received = sum(b.paid_amount for b in bills)

    udhar_added = sum(
        (b.total_amount - b.paid_amount)
        for b in bills
        if b.bill_type == models.BillType.UDHAR
    )

    return {
        "from": from_date,
        "to": to_date,
        "total_bills": len(bills),
        "total_sales": total_sales,
        "cash_received": total_received,
        "udhar_added": udhar_added,
    }

# -------------------------
# MONTHLY SUMMARY (BY BILL TYPE)
# -------------------------
@router.get("/summary/monthly")
def monthly_summary(
    year: int,
    month: int,
    db: Session = Depends(get_db)
):
    bills = (
        db.query(models.Bill)
        .filter(func.strftime("%Y", models.Bill.created_at) == str(year))
        .filter(func.strftime("%m", models.Bill.created_at) == f"{month:02d}")
        .all()
    )

    def summarize(bill_type):
        filtered = [b for b in bills if b.bill_type == bill_type]

        total_sales = sum(b.total_amount for b in filtered)
        cash_received = sum(b.paid_amount for b in filtered)

        udhar_added = sum(
            (b.total_amount - b.paid_amount)
            for b in filtered
            if bill_type == models.BillType.UDHAR
        )

        return {
            "total_bills": len(filtered),
            "total_sales": total_sales,
            "cash_received": cash_received,
            "udhar_added": udhar_added,
        }

    return {
        "year": year,
        "month": month,
        "GST": summarize(models.BillType.GST),
        "NON_GST": summarize(models.BillType.NON_GST),
        "UDHAR": summarize(models.BillType.UDHAR),
    }