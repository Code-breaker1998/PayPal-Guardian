from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PublicKey,
)
from .merchant_trust.engine import MERCHANT_REGISTRY
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .phase6_models import Approval, PayPalOrder
from .phase6_router import router as phase6_router
from .config import settings
from .database import (
    Base,
    engine,
    get_db,
    SessionLocal,
)
from .decision_engine import evaluate
from .merchant_trust.engine import (
    evaluate as evaluate_merchant,
)
from .models import (
    Agent,
    AuditEvent,
    MerchantTrustEvidence,
    PaymentIntent,
    Policy,
)
from .schemas import (
    AgentRegister,
    DecisionResponse,
    PaymentIntentCreate,
)
from .security import (
    assert_time_valid,
    calculate_payload_hash,
    verify_signature,
)
from .trust_hardening import (
    approve_agent_record,
    validate_item_total,
    validate_registered_category,
)
from .browser_discovery_models import (
    DiscoveredMerchant,
)
from .browser_discovery_router import (
    router as browser_discovery_router,
)

app = FastAPI(
    title="PayPal Guardian API",
    version="0.5.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.frontend_origin,
        settings.demo_agent_origin,
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(phase6_router)
app.include_router(browser_discovery_router)

@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(
        bind=engine
    )

    with SessionLocal() as db:
        active_policy = db.scalar(
            select(Policy).where(
                Policy.enabled.is_(True)
            )
        )

        if active_policy is None:
            db.add(Policy())
            db.commit()


def get_current_policy(
    db: Session,
) -> Policy:
    policy = db.scalar(
        select(Policy)
        .where(
            Policy.enabled.is_(True)
        )
        .order_by(
            Policy.version.desc()
        )
    )

    if policy is None:
        raise HTTPException(
            status_code=500,
            detail="No active policy is configured",
        )

    return policy


@app.get("/health")
def health(
    db: Session = Depends(get_db),
) -> dict[str, str]:
    db.execute(
        text("SELECT 1")
    )

    return {
        "status": "healthy",
        "service": "guardian-api",
        "database": "connected",
        "merchant_trust": "enabled",
    }


@app.post(
    "/api/v1/agents",
    status_code=201,
)
def register_agent(
    agent_request: AgentRegister,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    existing_agent = db.scalar(
        select(Agent).where(
            Agent.agent_id
            == agent_request.agent_id
        )
    )

    if existing_agent is not None:
        if (
            existing_agent.public_key_pem
            != agent_request.public_key_pem
        ):
            raise HTTPException(
                status_code=409,
                detail="Agent key mismatch",
            )

        return {
            "agent_id": existing_agent.agent_id,
            "status": existing_agent.status,
            "registered": False,
        }

    try:
        public_key = (
            serialization.load_pem_public_key(
                agent_request.public_key_pem.encode(
                    "utf-8"
                )
            )
        )

        if not isinstance(
            public_key,
            Ed25519PublicKey,
        ):
            raise ValueError(
                "The supplied key is not Ed25519"
            )

    except (
        ValueError,
        TypeError,
    ) as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                "A valid Ed25519 public key "
                "is required"
            ),
        ) from exc

    allowed_purposes = [
        purpose.strip().upper()
        for purpose
        in agent_request.allowed_purposes
    ]

    agent = Agent(
        agent_id=agent_request.agent_id,
        name=agent_request.name,
        public_key_pem=(
            agent_request.public_key_pem
        ),
        allowed_purposes=allowed_purposes,
    )

    registration_event = AuditEvent(
        entity_id=agent_request.agent_id,
        event_type="AGENT_REGISTERED",
        payload={
            "agent_id": agent_request.agent_id,
            "name": agent_request.name,
            "allowed_purposes": allowed_purposes,
        },
    )

    db.add_all(
        [
            agent,
            registration_event,
        ]
    )

    try:
        db.commit()

    except IntegrityError as exc:
        db.rollback()

        raise HTTPException(
            status_code=409,
            detail="Agent registration conflict",
        ) from exc

    return {
        "agent_id": agent_request.agent_id,
        "status": "PENDING",
        "registered": True,
    }


@app.get("/api/v1/dashboard")
def dashboard(
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    payment_intents = list(
        db.scalars(
            select(PaymentIntent)
            .order_by(
                PaymentIntent.id.desc()
            )
            .limit(20)
        )
    )

    return {
        "tagline": (
            "AI Agents Spend. "
            "Guardian Keeps You in Control."
        ),
        "counts": {
            "total": len(payment_intents),
            "allow": sum(
                payment_intent.decision == "ALLOW"
                for payment_intent
                in payment_intents
            ),
            "review": sum(
                payment_intent.decision == "REVIEW"
                for payment_intent
                in payment_intents
            ),
            "block": sum(
                payment_intent.decision == "BLOCK"
                for payment_intent
                in payment_intents
            ),
        },
        "recent": [
            {
                "intent_id": (
                    payment_intent
                    .external_intent_id
                ),
                "merchant": (
                    payment_intent.merchant_name
                ),
                "domain": (
                    payment_intent.merchant_domain
                ),
                "trust_level": (
                    payment_intent.trust_level
                ),
                "amount": float(
                    payment_intent.amount
                ),
                "currency": (
                    payment_intent.currency
                ),
                "decision": (
                    payment_intent.decision
                ),
                "risk_score": (
                    payment_intent.risk_score
                ),
            }
            for payment_intent
            in payment_intents
        ],
    }


@app.post(
    "/api/v1/payment-intents",
    response_model=DecisionResponse,
    status_code=201,
)
async def create_payment_intent(
    payment_intent: PaymentIntentCreate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    agent = db.scalar(
        select(Agent).where(
            Agent.agent_id
            == payment_intent.agent_id
        )
    )

    if (
        agent is None
        or agent.status != "ACTIVE"
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Agent is not registered "
                "or active"
            ),
        )

    requested_purpose = (
        payment_intent
        .purpose
        .strip()
        .upper()
    )

    allowed_purposes = {
        purpose.strip().upper()
        for purpose
        in agent.allowed_purposes
    }

    if requested_purpose not in allowed_purposes:
        raise HTTPException(
            status_code=403,
            detail="Purpose is outside agent authority",
        )

    try:
        assert_time_valid(
            payment_intent
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    signature_is_valid = verify_signature(
        agent.public_key_pem,
        payment_intent,
    )

    if not signature_is_valid:
        raise HTTPException(
            status_code=401,
            detail="Invalid agent signature",
        )

    existing_intent = db.scalar(
        select(PaymentIntent).where(
            (
                PaymentIntent.external_intent_id
                == payment_intent.intent_id
            )
            | (
                PaymentIntent.nonce
                == payment_intent.nonce
            )
        )
    )

    if existing_intent is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Intent ID or nonce "
                "has already been used"
            ),
        )

    validate_item_total(payment_intent)

    merchant_record = MERCHANT_REGISTRY.get(
        payment_intent.merchant.id
    )
    if merchant_record is None:
        raise HTTPException(
            status_code=403,
            detail="Merchant is not registered",
        )
    validate_registered_category(
        payment_intent,
        merchant_record,
    )

    merchant_trust = await evaluate_merchant(
        payment_intent.merchant
    )

    active_policy = get_current_policy(
        db
    )

    guardian_decision = evaluate(
        payment_intent=payment_intent,
        policy=active_policy,
        merchant_trust=merchant_trust,
    )

    if guardian_decision["decision"] == "REVIEW":
        db.add(
            Approval(
                payment_intent_id=payment_intent.intent_id,
                status="PENDING",
            )
        )

    intent_payload_hash = calculate_payload_hash(
        payment_intent
    )

    trust_evidence = MerchantTrustEvidence(
        evidence_id=merchant_trust[
            "evidence_id"
        ],
        payment_intent_id=(
            payment_intent.intent_id
        ),
        submitted_url=merchant_trust[
            "submitted_url"
        ],
        normalized_hostname=merchant_trust[
            "normalized_hostname"
        ],
        registered_domain=merchant_trust[
            "registered_domain"
        ],
        seller_id=merchant_trust[
            "seller_id"
        ],
        tls_result=merchant_trust[
            "tls"
        ],
        trust_score=merchant_trust[
            "trust_score"
        ],
        trust_level=merchant_trust[
            "trust_level"
        ],
        decision=merchant_trust[
            "decision"
        ],
        reason_codes=merchant_trust[
            "reason_codes"
        ],
        evidence_hash=merchant_trust[
            "evidence_hash"
        ],
    )

    payment_intent_record = PaymentIntent(
        external_intent_id=(
            payment_intent.intent_id
        ),
        agent_id=payment_intent.agent_id,
        nonce=payment_intent.nonce,
        payload_hash=intent_payload_hash,
        merchant_id=(
            payment_intent.merchant.id
        ),
        merchant_name=(
            payment_intent.merchant.name
        ),
        merchant_category=(
            payment_intent.merchant.category
        ),
        merchant_domain=merchant_trust[
            "normalized_hostname"
        ],
        product_url=(
            payment_intent
            .merchant
            .product_url
        ),
        seller_id=(
            payment_intent
            .merchant
            .seller_id
        ),
        trust_evidence_id=merchant_trust[
            "evidence_id"
        ],
        trust_level=merchant_trust[
            "trust_level"
        ],
        amount=payment_intent.amount,
        currency=(
            payment_intent
            .currency
            .upper()
        ),
        purchase_type=(
            payment_intent.purchase_type
        ),
        decision=guardian_decision[
            "decision"
        ],
        risk_score=guardian_decision[
            "risk_score"
        ],
        reason_codes=guardian_decision[
            "reason_codes"
        ],
    )

    signature_event = AuditEvent(
        entity_id=payment_intent.intent_id,
        event_type="SIGNATURE_VERIFIED",
        payload={
            "agent_id": payment_intent.agent_id,
            "payload_hash": intent_payload_hash,
        },
    )

    merchant_trust_event = AuditEvent(
        entity_id=payment_intent.intent_id,
        event_type="MERCHANT_TRUST_DECIDED",
        payload=merchant_trust,
    )

    decision_event = AuditEvent(
        entity_id=payment_intent.intent_id,
        event_type="GUARDIAN_DECISION",
        payload=guardian_decision,
    )

    db.add_all(
        [
            trust_evidence,
            payment_intent_record,
            signature_event,
            merchant_trust_event,
            decision_event,
        ]
    )

    try:
        db.commit()

    except IntegrityError as exc:
        db.rollback()

        raise HTTPException(
            status_code=409,
            detail=(
                "Duplicate payment intent "
                "or merchant trust evidence"
            ),
        ) from exc

    return {
        "intent_id": payment_intent.intent_id,
        "signature_verified": True,
        **guardian_decision,
    }


@app.get(
    "/api/v1/payment-intents/{intent_id}/audit"
)
def get_payment_intent_audit(
    intent_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    audit_events = list(
        db.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.entity_id
                == intent_id
            )
            .order_by(
                AuditEvent.id
            )
        )
    )

    return {
        "intent_id": intent_id,
        "events": [
            {
                "event_type": (
                    audit_event.event_type
                ),
                "payload": (
                    audit_event.payload
                ),
                "created_at": (
                    audit_event
                    .created_at
                    .isoformat()
                ),
            }
            for audit_event
            in audit_events
        ],
    }

@app.post("/api/v1/admin/agents/{agent_id}/approve")
def approve_agent(
    agent_id: str,
    db: Session = Depends(get_db),
) -> dict:
    return approve_agent_record(agent_id, db)