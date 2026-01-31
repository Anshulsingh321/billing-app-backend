from pydantic import BaseModel
from typing import List, Optional

class CustomerCreate(BaseModel):
    name: str
    phone: Optional[str] = None
    address: Optional[str] = None


class BillCreate(BaseModel):
    customer_id: int
    bill_type: str  # GST / NON_GST / UDHAR


class BillItemCreate(BaseModel):
    item_name: str
    quantity: float
    rate: Optional[float] = None
    unit: Optional[str] = None

class BillPaymentCreate(BaseModel):
    amount: float

class BillAdjustmentCreate(BaseModel):
    amount: float   # +ve = charge, -ve = return
    reason: str | None = None

class BillCorrectionRequest(BaseModel):
    bill_id: int
    command: str

class VoiceCorrectionRequest(BaseModel):
    bill_id: int
    command: str

class VisionTextNormalizeRequest(BaseModel):
    lines: List[str]