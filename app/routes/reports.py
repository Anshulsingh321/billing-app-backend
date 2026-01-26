from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import date, datetime

from app.database import get_db
from app import models

router = APIRouter(
    prefix="/reports",
    tags=["Reports"]
)

@router.get("/daily")
def daily_report(
    report_date: date | None = None,
    db: Session = Depends(get_db)
):
    """
    Daily sales report.
    If no date is provided, defaults to today.
    """
    if report_date is None:
        report_date = date.today()

    start_dt = datetime.combine(report_date, datetime.min.time())
    end_dt = datetime.combine(report_date, datetime.max.time())

    bills = (
        db.query(models.Bill)
        .filter(
            models.Bill.created_at >= start_dt,
            models.Bill.created_at <= end_dt
        )
        .all()
    )

    total_bills = len(bills)
    total_sales = sum(b.total_amount for b in bills)

    by_bill_type = {
        "GST": 0,
        "NON_GST": 0,
        "UDHAR": 0
    }

    cash_received = 0
    udhar_added = 0
    udhar_collected = 0

    for bill in bills:
        by_bill_type[bill.bill_type.value] += bill.total_amount

        for payment in bill.payments:
            cash_received += payment.amount

        if bill.bill_type.value == "UDHAR":
            udhar_added += bill.total_amount
            udhar_collected += bill.paid_amount

    return {
        "date": report_date,
        "total_bills": total_bills,
        "total_sales": total_sales,
        "by_bill_type": by_bill_type,
        "payments": {
            "cash_received": cash_received,
            "udhar_added": udhar_added,
            "udhar_collected": udhar_collected,
        }
    }
