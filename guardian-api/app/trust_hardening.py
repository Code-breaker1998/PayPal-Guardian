from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Agent, AuditEvent


def validate_item_total(payment_intent) -> None:
    calculated_total = round(
        sum(item.unit_price * item.quantity for item in payment_intent.items),
        2,
    )
    submitted_total = round(payment_intent.amount, 2)
    if calculated_total != submitted_total:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INTENT_AMOUNT_MISMATCH",
                "calculated_total": calculated_total,
                "submitted_total": submitted_total,
            },
        )


def validate_registered_category(payment_intent, merchant_record: dict) -> None:
    submitted = payment_intent.merchant.category.strip().upper()
    registered = merchant_record["category"].strip().upper()
    if submitted != registered:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "MERCHANT_CATEGORY_MISMATCH",
                "submitted_category": submitted,
                "registered_category": registered,
            },
        )


def approve_agent_record(agent_id: str, db: Session) -> dict:
    agent = db.scalar(select(Agent).where(Agent.agent_id == agent_id))
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent.status = "ACTIVE"
    db.add(AuditEvent(
        entity_id=agent_id,
        event_type="AGENT_APPROVED",
        payload={"agent_id": agent_id, "status": "ACTIVE"},
    ))
    db.commit()
    return {"agent_id": agent_id, "status": "ACTIVE"}
