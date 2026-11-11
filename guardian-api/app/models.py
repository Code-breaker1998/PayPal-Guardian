from datetime import datetime
from sqlalchemy import Boolean, DateTime, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    public_key_pem: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    allowed_purposes: Mapped[list] = mapped_column(JSON, default=lambda:["PRODUCT_PURCHASE"])
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Policy(Base):
    __tablename__ = "policies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="Default Guardian Policy")
    single_transaction_limit: Mapped[float] = mapped_column(Numeric(12,2), default=200)
    approval_threshold: Mapped[float] = mapped_column(Numeric(12,2), default=75)
    allowed_categories: Mapped[list] = mapped_column(JSON, default=lambda:["ELECTRONICS"])
    blocked_categories: Mapped[list] = mapped_column(JSON, default=lambda:["GAMBLING","CRYPTOCURRENCY"])
    new_merchant_requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    subscriptions_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class PaymentIntent(Base):
    __tablename__ = "payment_intents"
    id: Mapped[int] = mapped_column(primary_key=True)
    external_intent_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    agent_id: Mapped[str] = mapped_column(String(100), index=True)
    nonce: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    merchant_id: Mapped[str] = mapped_column(String(100))
    merchant_name: Mapped[str] = mapped_column(String(200))
    merchant_category: Mapped[str] = mapped_column(String(100))
    merchant_domain: Mapped[str] = mapped_column(String(255))
    product_url: Mapped[str] = mapped_column(Text)
    seller_id: Mapped[str] = mapped_column(String(100))
    trust_evidence_id: Mapped[str] = mapped_column(String(100), index=True)
    trust_level: Mapped[str] = mapped_column(String(30))
    amount: Mapped[float] = mapped_column(Numeric(12,2))
    currency: Mapped[str] = mapped_column(String(3))
    purchase_type: Mapped[str] = mapped_column(String(30))
    decision: Mapped[str] = mapped_column(String(20))
    risk_score: Mapped[int] = mapped_column(Integer)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class MerchantTrustEvidence(Base):
    __tablename__ = "merchant_trust_evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    payment_intent_id: Mapped[str] = mapped_column(String(100), index=True)
    submitted_url: Mapped[str] = mapped_column(Text)
    normalized_hostname: Mapped[str] = mapped_column(String(255))
    registered_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    seller_id: Mapped[str] = mapped_column(String(100))
    tls_result: Mapped[dict] = mapped_column(JSON)
    trust_score: Mapped[int] = mapped_column(Integer)
    trust_level: Mapped[str] = mapped_column(String(30))
    decision: Mapped[str] = mapped_column(String(20))
    reason_codes: Mapped[list] = mapped_column(JSON)
    evidence_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[str] = mapped_column(String(100), index=True)
    event_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(20),default="PENDING")