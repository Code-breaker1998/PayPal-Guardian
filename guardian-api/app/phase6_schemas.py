from pydantic import BaseModel, Field


class ApprovalDecisionRequest(BaseModel):
    decided_by: str = Field(min_length=2, max_length=160)
    note: str | None = Field(default=None, max_length=500)


class ApprovalResponse(BaseModel):
    payment_intent_id: str
    status: str
    decided_by: str | None = None
    decision_note: str | None = None


class PayPalOrderResponse(BaseModel):
    payment_intent_id: str
    paypal_order_id: str
    status: str
    approval_url: str | None = None
    capture_id: str | None = None
