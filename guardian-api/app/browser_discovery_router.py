from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .browser_discovery_models import DiscoveredMerchant
from .database import get_db
from .merchant_trust.engine import (
    LOCAL_DOMAIN_BLOCKLIST,
    MERCHANT_REGISTRY,
    detect_lookalike_domain,
    normalize_url,
    validate_tls_certificate,
)

router = APIRouter(prefix="/api/v1/merchants", tags=["Merchant Discovery"])


class PageProduct(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    price: float = Field(gt=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    sku: str | None = None
    rating: float | None = None
    availability: str | None = None
    seller_name: str | None = None
    image_url: str | None = None
    category: str | None = None
    source: str


class MerchantDiscoveryRequest(BaseModel):
    page_url: str
    page_title: str | None = None
    hostname: str
    product: PageProduct
    confidence: str
    extracted_at: datetime


@router.post("/discover")
async def discover_merchant(
    request: MerchantDiscoveryRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        normalized_hostname, port = normalize_url(request.page_url)
    except ValueError as exc:
        return {
            "decision": "BLOCK",
            "merchant_status": "REJECTED",
            "trust_level": "HIGH_RISK",
            "reason_codes": [str(exc)],
            "explanation": "The page URL failed Guardian validation.",
        }

    if normalized_hostname != request.hostname.lower().rstrip("."):
        raise HTTPException(status_code=422, detail="Hostname evidence mismatch")

    registered = next(
        (
            record
            for record in MERCHANT_REGISTRY.values()
            if normalized_hostname == record["domain"]
            or normalized_hostname.endswith(f'.{record["domain"]}')
        ),
        None,
    )

    reason_codes: list[str] = []
    if normalized_hostname in LOCAL_DOMAIN_BLOCKLIST:
        reason_codes.append("LOCAL_THREAT_LIST_HIT")

    registered_domain = registered["domain"] if registered else None
    reason_codes.extend(
        detect_lookalike_domain(normalized_hostname, registered_domain)
    )

    tls_result = await validate_tls_certificate(normalized_hostname, port)
    if not tls_result.get("valid"):
        reason_codes.append("TLS_VALIDATION_FAILED")

    hard_block = bool(reason_codes)
    if hard_block:
        status = "REJECTED"
        decision = "BLOCK"
        trust_level = "HIGH_RISK"
        explanation = "Guardian found a blocking website security signal."
    elif registered:
        status = "VERIFIED"
        decision = "ALLOW"
        trust_level = "VERIFIED"
        reason_codes.append("REGISTERED_MERCHANT")
        explanation = "The merchant is registered and its live TLS certificate is valid."
    else:
        status = "PENDING_VERIFICATION"
        decision = "REVIEW"
        trust_level = "MEDIUM"
        reason_codes.append("NEW_MERCHANT_DISCOVERED")
        explanation = "The domain passed live TLS checks but is new and requires approval."

    merchant = db.scalar(
        select(DiscoveredMerchant).where(
            DiscoveredMerchant.hostname == normalized_hostname
        )
    )
    if merchant is None:
        merchant = DiscoveredMerchant(
            hostname=normalized_hostname,
            display_name=request.product.seller_name or normalized_hostname,
        )
        db.add(merchant)

    merchant.status = status
    merchant.tls_result = tls_result
    merchant.reason_codes = sorted(set(reason_codes))
    merchant.last_seen_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "decision": decision,
        "merchant_status": status,
        "trust_level": trust_level,
        "reason_codes": merchant.reason_codes,
        "explanation": explanation,
        "normalized_hostname": normalized_hostname,
        "tls": tls_result,
        "product": request.product.model_dump(),
    }


@router.get("/discovered")
def list_discovered_merchants(
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    merchants = list(
        db.scalars(
            select(DiscoveredMerchant).order_by(
                DiscoveredMerchant.last_seen_at.desc()
            )
        )
    )
    return [
        {
            "hostname": merchant.hostname,
            "display_name": merchant.display_name,
            "status": merchant.status,
            "reason_codes": merchant.reason_codes,
            "tls": merchant.tls_result,
            "first_seen_at": merchant.first_seen_at.isoformat(),
            "last_seen_at": merchant.last_seen_at.isoformat(),
        }
        for merchant in merchants
    ]
