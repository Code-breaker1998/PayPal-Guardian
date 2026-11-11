from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import get_db
from .models import AuditEvent, PaymentIntent
from .paypal_client import (
    PayPalAPIError,
    PayPalConfigurationError,
    capture_order,
    create_order,
)
from .phase6_models import Approval, PayPalOrder
from .phase6_schemas import (
    ApprovalDecisionRequest,
    ApprovalResponse,
    PayPalOrderResponse,
)

router = APIRouter(prefix="/api/v1", tags=["Approvals and PayPal"])


def _approval_url(paypal_response: dict[str, Any]) -> str | None:
    for link in paypal_response.get("links", []):
        if link.get("rel") in {"payer-action", "approve"}:
            return link.get("href")
    return None


def _capture_id(paypal_response: dict[str, Any]) -> str | None:
    for purchase_unit in paypal_response.get("purchase_units", []):
        captures = purchase_unit.get("payments", {}).get("captures", [])
        if captures:
            return captures[0].get("id")
    return None


@router.get("/approvals")
def list_approvals(
    status: str | None = None,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    query = select(Approval).order_by(Approval.id.desc())
    if status:
        query = query.where(Approval.status == status.upper())
    output: list[dict[str, Any]] = []
    for approval in db.scalars(query):
        intent = db.scalar(
            select(PaymentIntent).where(
                PaymentIntent.external_intent_id == approval.payment_intent_id
            )
        )
        output.append(
            {
                "payment_intent_id": approval.payment_intent_id,
                "status": approval.status,
                "decided_by": approval.decided_by,
                "decision_note": approval.decision_note,
                "merchant": intent.merchant_name if intent else None,
                "amount": float(intent.amount) if intent else None,
                "currency": intent.currency if intent else None,
                "risk_score": intent.risk_score if intent else None,
                "reason_codes": intent.reason_codes if intent else [],
            }
        )
    return output


def _get_review_intent(intent_id: str, db: Session) -> PaymentIntent:
    intent = db.scalar(
        select(PaymentIntent).where(
            PaymentIntent.external_intent_id == intent_id
        )
    )
    if intent is None:
        raise HTTPException(status_code=404, detail="Payment intent not found")
    if intent.decision != "REVIEW":
        raise HTTPException(
            status_code=409,
            detail="Only REVIEW payment intents require human approval",
        )
    return intent


@router.post(
    "/payment-intents/{intent_id}/approve",
    response_model=ApprovalResponse,
)
def approve_intent(
    intent_id: str,
    request: ApprovalDecisionRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _get_review_intent(intent_id, db)
    approval = db.scalar(
        select(Approval).where(Approval.payment_intent_id == intent_id)
    )
    if approval is None:
        approval = Approval(payment_intent_id=intent_id)
        db.add(approval)
    if approval.status != "PENDING":
        raise HTTPException(status_code=409, detail="Approval already decided")
    approval.status = "APPROVED"
    approval.decided_by = request.decided_by
    approval.decision_note = request.note
    approval.decided_at = datetime.now(timezone.utc)
    db.add(
        AuditEvent(
            entity_id=intent_id,
            event_type="HUMAN_APPROVED",
            payload={"decided_by": request.decided_by, "note": request.note},
        )
    )
    db.commit()
    return {
        "payment_intent_id": intent_id,
        "status": approval.status,
        "decided_by": approval.decided_by,
        "decision_note": approval.decision_note,
    }


@router.post(
    "/payment-intents/{intent_id}/reject",
    response_model=ApprovalResponse,
)
def reject_intent(
    intent_id: str,
    request: ApprovalDecisionRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _get_review_intent(intent_id, db)
    approval = db.scalar(
        select(Approval).where(Approval.payment_intent_id == intent_id)
    )
    if approval is None:
        approval = Approval(payment_intent_id=intent_id)
        db.add(approval)
    if approval.status != "PENDING":
        raise HTTPException(status_code=409, detail="Approval already decided")
    approval.status = "REJECTED"
    approval.decided_by = request.decided_by
    approval.decision_note = request.note
    approval.decided_at = datetime.now(timezone.utc)
    db.add(
        AuditEvent(
            entity_id=intent_id,
            event_type="HUMAN_REJECTED",
            payload={"decided_by": request.decided_by, "note": request.note},
        )
    )
    db.commit()
    return {
        "payment_intent_id": intent_id,
        "status": approval.status,
        "decided_by": approval.decided_by,
        "decision_note": approval.decision_note,
    }


@router.post(
    "/payment-intents/{intent_id}/paypal-order",
    response_model=PayPalOrderResponse,
    status_code=201,
)
async def create_paypal_order(
    intent_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    intent = db.scalar(
        select(PaymentIntent).where(
            PaymentIntent.external_intent_id == intent_id
        )
    )
    if intent is None:
        raise HTTPException(status_code=404, detail="Payment intent not found")
    if intent.decision == "BLOCK":
        raise HTTPException(status_code=403, detail="Blocked intent cannot be paid")
    if intent.decision == "REVIEW":
        approval = db.scalar(
            select(Approval).where(Approval.payment_intent_id == intent_id)
        )
        if approval is None or approval.status != "APPROVED":
            raise HTTPException(
                status_code=403,
                detail="Human approval is required before PayPal order creation",
            )
    existing = db.scalar(
        select(PayPalOrder).where(PayPalOrder.payment_intent_id == intent_id)
    )
    if existing is not None:
        return {
            "payment_intent_id": intent_id,
            "paypal_order_id": existing.paypal_order_id,
            "status": existing.status,
            "approval_url": existing.approval_url,
            "capture_id": existing.capture_id,
        }
    try:
        paypal_response = await create_order(
            intent_id=intent_id,
            amount=f"{Decimal(intent.amount):.2f}",
            currency=intent.currency,
            description=f"{intent.merchant_name} purchase",
        )
    except PayPalConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PayPalAPIError as exc:
        raise HTTPException(status_code=502, detail=exc.message) from exc
    order = PayPalOrder(
        payment_intent_id=intent_id,
        paypal_order_id=paypal_response["id"],
        status=paypal_response["status"],
        approval_url=_approval_url(paypal_response),
        raw_response=paypal_response,
    )
    db.add(order)
    db.add(
        AuditEvent(
            entity_id=intent_id,
            event_type="PAYPAL_ORDER_CREATED",
            payload={
                "paypal_order_id": order.paypal_order_id,
                "status": order.status,
                "approval_url": order.approval_url,
            },
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="PayPal order already exists") from exc
    return {
        "payment_intent_id": intent_id,
        "paypal_order_id": order.paypal_order_id,
        "status": order.status,
        "approval_url": order.approval_url,
        "capture_id": None,
    }


@router.post(
    "/paypal/orders/{order_id}/capture",
    response_model=PayPalOrderResponse,
)
async def capture_paypal_order(
    order_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    order = db.scalar(
        select(PayPalOrder).where(PayPalOrder.paypal_order_id == order_id)
    )
    if order is None:
        raise HTTPException(status_code=404, detail="PayPal order not found")
    if order.status == "COMPLETED":
        return {
            "payment_intent_id": order.payment_intent_id,
            "paypal_order_id": order.paypal_order_id,
            "status": order.status,
            "approval_url": order.approval_url,
            "capture_id": order.capture_id,
        }
    try:
        paypal_response = await capture_order(order_id)
    except PayPalConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PayPalAPIError as exc:
        raise HTTPException(status_code=502, detail=exc.message) from exc
    order.status = paypal_response["status"]
    order.capture_id = _capture_id(paypal_response)
    order.raw_response = paypal_response
    db.add(
        AuditEvent(
            entity_id=order.payment_intent_id,
            event_type="PAYPAL_ORDER_CAPTURED",
            payload={
                "paypal_order_id": order.paypal_order_id,
                "capture_id": order.capture_id,
                "status": order.status,
            },
        )
    )
    db.commit()
    return {
        "payment_intent_id": order.payment_intent_id,
        "paypal_order_id": order.paypal_order_id,
        "status": order.status,
        "approval_url": order.approval_url,
        "capture_id": order.capture_id,
    }
