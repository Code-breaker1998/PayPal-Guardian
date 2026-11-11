from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import os

GUARDIAN_API_URL = os.getenv("GUARDIAN_API_URL", "http://guardian-api:8000")

router = APIRouter(prefix="/agent/browser-extension-page", tags=["Browser Product Scanner"])


class BrowserProduct(BaseModel):
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


class BrowserPageEvidence(BaseModel):
    page_url: str
    page_title: str | None = None
    hostname: str
    product: BrowserProduct
    confidence: str
    extracted_at: datetime


@router.post("/analyze")
async def analyze_browser_page(
    evidence: BrowserPageEvidence,
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{GUARDIAN_API_URL}/api/v1/merchants/discover",
                json=evidence.model_dump(mode="json"),
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail="Guardian merchant discovery is unavailable",
        ) from exc

    body = response.json()
    if not response.is_success:
        raise HTTPException(
            status_code=response.status_code,
            detail=body.get("detail", body),
        )

    product = evidence.product
    if evidence.confidence != "HIGH":
        body["decision"] = "REVIEW"
        body["trust_level"] = "MEDIUM"
        body["reason_codes"] = sorted(
            set(body.get("reason_codes", []) + ["LOW_EXTRACTION_CONFIDENCE"])
        )
        body["explanation"] = (
            "Product data was only partially extracted and requires review."
        )

    body["recommendation"] = {
        "product_name": product.name,
        "price": product.price,
        "currency": product.currency or "UNKNOWN",
        "seller": product.seller_name or evidence.hostname,
        "source": product.source,
        "message": (
            f"Detected {product.name} at "
            f"{product.currency or ''} {product.price:.2f}. "
            f"Guardian decision: {body['decision']}."
        ),
    }
    return body
