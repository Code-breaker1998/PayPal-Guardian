from datetime import datetime, timezone

from sqlalchemy import DateTime, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_intent_id: Mapped[str] = mapped_column(
        String(100), unique=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default="PENDING", index=True
    )
    decided_by: Mapped[str | None] = mapped_column(
        String(160), nullable=True
    )
    decision_note: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PayPalOrder(Base):
    __tablename__ = "paypal_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_intent_id: Mapped[str] = mapped_column(
        String(100), unique=True, index=True
    )
    paypal_order_id: Mapped[str] = mapped_column(
        String(100), unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(40), index=True)
    approval_url: Mapped[str | None] = mapped_column(
        String(1000), nullable=True
    )
    capture_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    raw_response: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
