from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    Field,
    model_validator,
)


class Item(BaseModel):
    sku: str
    name: str

    quantity: int = Field(
        ge=1,
        le=20,
    )

    unit_price: float = Field(
        gt=0,
    )


class Merchant(BaseModel):
    id: str
    name: str
    category: str
    domain: str
    product_url: str
    seller_id: str


class PaymentIntentCreate(BaseModel):
    intent_id: str
    agent_id: str
    purpose: str = "PRODUCT_PURCHASE"

    merchant: Merchant
    items: list[Item]

    currency: str = Field(
        default="USD",
        min_length=3,
        max_length=3,
    )

    amount: float = Field(
        gt=0,
    )

    purchase_type: Literal[
        "ONE_TIME",
        "SUBSCRIPTION",
    ] = "ONE_TIME"

    nonce: str = Field(
        min_length=16,
        max_length=100,
    )

    issued_at: datetime
    expires_at: datetime

    signature: str = Field(
        min_length=20,
    )

    @model_validator(mode="after")
    def validate_times(
        self,
    ) -> "PaymentIntentCreate":
        if (
            self.issued_at.tzinfo is None
            or self.expires_at.tzinfo is None
        ):
            raise ValueError(
                "timestamps must include timezone"
            )

        if self.expires_at <= self.issued_at:
            raise ValueError(
                "expires_at must be after issued_at"
            )

        intent_validity_seconds = (
            self.expires_at
            - self.issued_at
        ).total_seconds()

        if intent_validity_seconds > 600:
            raise ValueError(
                "intent validity cannot exceed "
                "10 minutes"
            )

        return self


class AgentRegister(BaseModel):
    agent_id: str
    name: str
    public_key_pem: str

    allowed_purposes: list[str] = Field(
        default_factory=lambda: [
            "PRODUCT_PURCHASE"
        ]
    )


class DecisionResponse(BaseModel):
    intent_id: str

    decision: Literal[
        "ALLOW",
        "REVIEW",
        "BLOCK",
    ]

    risk_score: int

    risk_level: Literal[
        "LOW",
        "MEDIUM",
        "HIGH",
    ]

    approval_required: bool

    reason_codes: list[str] = Field(
        default_factory=list,
    )

    explanation: str
    policy_version: int
    signature_verified: bool
