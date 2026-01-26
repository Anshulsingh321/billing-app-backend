from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
    Enum
)
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from app.database import Base


# ------------------------
# ENUMS
# ------------------------

class BillType(str, enum.Enum):
    GST = "GST"
    NON_GST = "NON_GST"
    UDHAR = "UDHAR"


class BillStatus(str, enum.Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"

class AdjustmentType(str, enum.Enum):
    ITEM_RETURN = "ITEM_RETURN"
    RATE_CORRECTION = "RATE_CORRECTION"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"


# ------------------------
# CUSTOMER
# ------------------------

class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    address = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    bills = relationship("Bill", back_populates="customer")


# ------------------------
# ITEM MASTER
# ------------------------

class ItemMaster(Base):
    __tablename__ = "item_master"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    rate = Column(Float, nullable=False)
    unit = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )


# ------------------------
# BILL
# ------------------------

class Bill(Base):
    __tablename__ = "bills"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)

    bill_type = Column(Enum(BillType), nullable=False)
    status = Column(Enum(BillStatus), default=BillStatus.OPEN)

    # Amounts (calculated at finalize)
    subtotal = Column(Float, default=0)
    gst_rate = Column(Float, default=0)        # % e.g. 18
    gst_amount = Column(Float, default=0)
    total_amount = Column(Float, default=0)

    paid_amount = Column(Float, default=0)

    # GST metadata (optional but future-proof)
    invoice_number = Column(String, unique=True, nullable=True)   # NON-GST / UDHAR
    gst_invoice_number = Column(String, nullable=True)            # GST only
    gstin = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    customer = relationship("Customer", back_populates="bills")
    items = relationship(
        "BillItem",
        back_populates="bill",
        cascade="all, delete-orphan"
    )
    payments = relationship(
        "Payment",
        back_populates="bill",
        cascade="all, delete-orphan"
    )
    adjustments = relationship(
        "BillAdjustment",
        back_populates="bill",
        cascade="all, delete-orphan"
    )


# ------------------------
# BILL ITEMS
# ------------------------

class BillItem(Base):
    __tablename__ = "bill_items"

    id = Column(Integer, primary_key=True, index=True)
    bill_id = Column(Integer, ForeignKey("bills.id"), nullable=False)

    item_name = Column(String, nullable=False)
    quantity = Column(Float, nullable=False)
    rate = Column(Float, nullable=False)
    unit = Column(String, nullable=True)

    subtotal = Column(Float, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    bill = relationship("Bill", back_populates="items")


# ------------------------
# PAYMENTS
# ------------------------

class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    bill_id = Column(Integer, ForeignKey("bills.id"), nullable=False)

    amount = Column(Float, nullable=False)
    method = Column(String, nullable=True)  # CASH / UPI / BANK / etc

    created_at = Column(DateTime, default=datetime.utcnow)

    bill = relationship("Bill", back_populates="payments")


# ------------------------
# BILL ADJUSTMENTS
# ------------------------

class BillAdjustment(Base):
    __tablename__ = "bill_adjustments"

    id = Column(Integer, primary_key=True, index=True)
    bill_id = Column(Integer, ForeignKey("bills.id"), nullable=False)

    adjustment_type = Column(Enum(AdjustmentType), nullable=False)

    amount_delta = Column(Float, nullable=False)
    # +ve = extra charge, -ve = refund

    note = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    bill = relationship("Bill", back_populates="adjustments")