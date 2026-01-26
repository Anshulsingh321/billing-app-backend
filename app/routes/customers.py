from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import SessionLocal
from .. import models, schemas
from sqlalchemy import func
from fastapi import Query
from fastapi.responses import FileResponse
from app.pdf_utils import generate_customer_ledger_pdf

router = APIRouter(prefix="/customers", tags=["Customers"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/")
def create_customer(customer: schemas.CustomerCreate, db: Session = Depends(get_db)):
    new_customer = models.Customer(
        name=customer.name,
        phone=customer.phone,
        address=customer.address
    )
    db.add(new_customer)
    db.commit()
    db.refresh(new_customer)
    return new_customer

@router.get("/search")
def search_customer(
    q: str = Query(..., description="Name or phone"),
    db: Session = Depends(get_db)
):
    customers = db.query(models.Customer).filter(
        (models.Customer.name.ilike(f"%{q}%")) |
        (models.Customer.phone.ilike(f"%{q}%"))
    ).all()

    result = []

    for customer in customers:
        total_due = 0

        for bill in customer.bills:
            due = bill.total_amount - bill.paid_amount
            if due > 0:
                total_due += due

        result.append({
            "customer_id": customer.id,
            "name": customer.name,
            "phone": customer.phone,
            "pending_amount": total_due
        })

    return result

@router.get("/{customer_id}/summary")
def customer_summary(customer_id: int, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).filter(
        models.Customer.id == customer_id
    ).first()

    if not customer:
        return {"error": "Customer not found"}

    pending = 0
    last_bill = None

    for bill in customer.bills:
        due = bill.total_amount - bill.paid_amount
        if due > 0:
            pending += due
        if not last_bill or bill.created_at > last_bill.created_at:
            last_bill = bill

    return {
        "customer_id": customer.id,
        "name": customer.name,
        "pending_amount": pending,
        "last_bill_id": last_bill.id if last_bill else None,
        "last_bill_date": last_bill.created_at if last_bill else None
    }

# Udhar Dashboard endpoint
@router.get("/udhar/outstanding")
def udhar_dashboard(db: Session = Depends(get_db)):
    rows = (
        db.query(
            models.Customer.id.label("customer_id"),
            models.Customer.name.label("customer_name"),
            models.Customer.phone.label("phone"),
            func.sum(models.Bill.total_amount).label("total_udhar"),
            func.sum(models.Bill.paid_amount).label("paid_amount"),
        )
        .join(models.Bill, models.Bill.customer_id == models.Customer.id)
        .filter(models.Bill.bill_type == models.BillType.UDHAR)
        .group_by(models.Customer.id)
        .all()
    )

    result = []

    for r in rows:
        remaining = (r.total_udhar or 0) - (r.paid_amount or 0)
        if remaining > 0:
            result.append({
                "customer_id": r.customer_id,
                "customer_name": r.customer_name,
                "phone": r.phone,
                "total_udhar": r.total_udhar,
                "paid_amount": r.paid_amount,
                "remaining_amount": remaining
            })

    return result


@router.get("/{customer_id}/outstanding")
def customer_udhar_outstanding(customer_id: int, db: Session = Depends(get_db)):
    customer = (
        db.query(models.Customer)
        .filter(models.Customer.id == customer_id)
        .first()
    )

    if not customer:
        return {"error": "Customer not found"}

    total_udhar = 0
    total_paid = 0

    for bill in customer.bills:
        if bill.bill_type == models.BillType.UDHAR:
            total_udhar += bill.total_amount
            total_paid += bill.paid_amount

    remaining = total_udhar - total_paid

    return {
        "customer_id": customer.id,
        "customer_name": customer.name,
        "total_udhar": total_udhar,
        "paid_amount": total_paid,
        "remaining_amount": remaining
    }

# -------------------------
# CUSTOMER LEDGER / STATEMENT
# -------------------------
@router.get("/{customer_id}/ledger")
def customer_ledger(customer_id: int, db: Session = Depends(get_db)):
    customer = (
        db.query(models.Customer)
        .filter(models.Customer.id == customer_id)
        .first()
    )

    if not customer:
        return {"error": "Customer not found"}

    entries = []

    # Bills → Debit
    for bill in customer.bills:
        entries.append({
            "date": bill.created_at,
            "type": "BILL",
            "reference": f"Bill #{bill.id}",
            "debit": bill.total_amount,
            "credit": 0
        })

    # Payments → Credit
    payments = (
        db.query(models.Payment)
        .join(models.Bill)
        .filter(models.Bill.customer_id == customer_id)
        .all()
    )

    for payment in payments:
        entries.append({
            "date": payment.created_at,
            "type": "PAYMENT",
            "reference": f"Payment (Bill #{payment.bill_id})",
            "debit": 0,
            "credit": payment.amount
        })

    # Sort by date
    entries.sort(key=lambda x: x["date"])

    # Running balance
    balance = 0
    ledger = []

    for e in entries:
        balance += e["debit"] - e["credit"]
        ledger.append({
            "date": e["date"],
            "type": e["type"],
            "reference": e["reference"],
            "debit": e["debit"],
            "credit": e["credit"],
            "balance": balance
        })

    return {
        "customer_id": customer.id,
        "customer_name": customer.name,
        "ledger": ledger,
        "closing_balance": balance
    }


# PDF ledger endpoint
@router.get("/{customer_id}/ledger/pdf")
def customer_ledger_pdf(customer_id: int, db: Session = Depends(get_db)):
    customer = (
        db.query(models.Customer)
        .filter(models.Customer.id == customer_id)
        .first()
    )

    if not customer:
        return {"error": "Customer not found"}

    entries = []

    # Bills → Debit
    for bill in customer.bills:
        entries.append({
            "date": bill.created_at,
            "type": "BILL",
            "debit": bill.total_amount,
            "credit": 0,
        })

    # Payments → Credit
    payments = (
        db.query(models.Payment)
        .join(models.Bill)
        .filter(models.Bill.customer_id == customer_id)
        .all()
    )

    for payment in payments:
        entries.append({
            "date": payment.created_at,
            "type": "PAYMENT",
            "debit": 0,
            "credit": payment.amount,
        })

    entries.sort(key=lambda x: x["date"])

    balance = 0
    ledger = []
    for e in entries:
        balance += e["debit"] - e["credit"]
        ledger.append({
            "date": e["date"],
            "type": e["type"],
            "debit": e["debit"],
            "credit": e["credit"],
            "balance": balance,
        })

    pdf_path = generate_customer_ledger_pdf(
        customer=customer,
        ledger=ledger
    )

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=f"ledger_customer_{customer.id}.pdf"
    )
