import base64
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from real_site_router import router as real_site_router
import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from agent import OLLAMA_MODEL, recommend
from browser_page_router import (
    router as browser_page_router,
)
from real_site_router import (
    router as real_site_router,
)

GUARDIAN_API_URL = os.getenv(
    "GUARDIAN_API_URL",
    "http://guardian-api:8000",
)

AGENT_ID = os.getenv(
    "AGENT_ID",
    "demo-shopping-agent",
)

AGENT_NAME = os.getenv(
    "AGENT_NAME",
    "Self-Hosted Shopping Agent",
)

PRIVATE_KEY_PATH = Path(
    os.getenv(
        "KEY_PATH",
        "/keys/demo-agent.pem",
    )
)

FRONTEND_ORIGIN = os.getenv(
    "FRONTEND_ORIGIN",
    "http://localhost:3000",
)


app = FastAPI(
    title="Self-Hosted Shopping Agent",
    version="0.6.0",
)

app.include_router(
    real_site_router
)

app.include_router(
    browser_page_router
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        FRONTEND_ORIGIN,
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ShoppingRequest(BaseModel):
    prompt: str = Field(
        min_length=8,
        max_length=500,
    )


def get_private_key() -> Ed25519PrivateKey:
    """
    Load the existing Ed25519 private key or create
    a new key if one does not already exist.
    """

    PRIVATE_KEY_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if PRIVATE_KEY_PATH.exists():
        existing_key = (
            serialization.load_pem_private_key(
                PRIVATE_KEY_PATH.read_bytes(),
                password=None,
            )
        )

        if not isinstance(
            existing_key,
            Ed25519PrivateKey,
        ):
            raise RuntimeError(
                "Stored private key is not an "
                "Ed25519 private key"
            )

        return existing_key

    private_key = Ed25519PrivateKey.generate()

    private_key_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=(
            serialization.NoEncryption()
        ),
    )

    PRIVATE_KEY_PATH.write_bytes(
        private_key_bytes
    )

    return private_key


def get_public_key_pem() -> str:
    """
    Derive the public key from the Agent private key
    and return it in PEM format.
    """

    private_key = get_private_key()

    public_key_bytes = (
        private_key
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=(
                serialization.PublicFormat
                .SubjectPublicKeyInfo
            ),
        )
    )

    return public_key_bytes.decode("utf-8")


def utc_isoformat(
    value: datetime,
) -> str:
    """
    Convert a timezone-aware datetime into consistent
    UTC ISO-8601 format ending with Z.
    """

    if value.tzinfo is None:
        raise ValueError(
            "datetime must include timezone"
        )

    return (
        value
        .astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def create_canonical_payload(
    payload: dict,
) -> bytes:
    """
    Convert a payment-intent dictionary into
    deterministic JSON bytes for signing.
    """

    canonical_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )

    return canonical_json.encode("utf-8")


def sign_payload(
    payload: dict,
) -> str:
    """
    Sign canonical payment-intent bytes using the
    Agent Ed25519 private key.
    """

    private_key = get_private_key()

    signature = private_key.sign(
        create_canonical_payload(payload)
    )

    return base64.b64encode(
        signature
    ).decode("utf-8")


def extract_hostname(
    product_url: str,
) -> str:
    """
    Extract and normalize the hostname from a
    selected product URL.
    """

    parsed_url = urlsplit(
        product_url.strip()
    )

    if parsed_url.scheme.lower() != "https":
        raise RuntimeError(
            "Selected product URL must use HTTPS"
        )

    if not parsed_url.hostname:
        raise RuntimeError(
            "Selected product has an invalid URL"
        )

    if parsed_url.username or parsed_url.password:
        raise RuntimeError(
            "Product URL contains embedded credentials"
        )

    return (
        parsed_url.hostname
        .rstrip(".")
        .lower()
        .encode("idna")
        .decode("ascii")
    )


def parse_error_response(
    response: httpx.Response,
) -> object:
    """
    Safely extract an error response returned by
    Guardian API.
    """

    try:
        return response.json()

    except ValueError:
        return response.text


@app.on_event("startup")
async def register_agent() -> None:
    """
    Submit the Agent public key to Guardian.

    A new Agent may remain PENDING until an
    administrator approves it.
    """

    registration_payload = {
        "agent_id": AGENT_ID,
        "name": AGENT_NAME,
        "public_key_pem": get_public_key_pem(),
        "allowed_purposes": [
            "PRODUCT_PURCHASE",
        ],
    }

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
        ) as client:
            response = await client.post(
                (
                    f"{GUARDIAN_API_URL}"
                    "/api/v1/agents"
                ),
                json=registration_payload,
            )

    except httpx.TimeoutException as exc:
        raise RuntimeError(
            "Guardian API timed out during "
            "Agent registration"
        ) from exc

    except httpx.HTTPError as exc:
        raise RuntimeError(
            "Unable to connect to Guardian API "
            "during Agent registration"
        ) from exc

    if response.status_code not in (200, 201):
        raise RuntimeError(
            "Agent registration failed: "
            f"{response.status_code} "
            f"{response.text}"
        )


@app.get("/health")
def health() -> dict:
    return {
        "status": "healthy",
        "service": "demo-agent",
        "agent_id": AGENT_ID,
        "model": OLLAMA_MODEL,
        "private_key_path": str(
            PRIVATE_KEY_PATH
        ),
    }


@app.post("/agent/recommend")
async def create_recommendation(
    request: ShoppingRequest,
) -> dict:
    """
    Return a local AI product recommendation without
    creating or signing a payment intent.
    """

    try:
        (
            recommendation,
            selected_product,
        ) = await recommend(
            request.prompt
        )

    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail=(
                "The local model did not respond "
                "within the configured timeout"
            ),
        ) from exc

    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Unable to communicate with "
                "the local model"
            ),
        ) from exc

    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    return {
        "model": OLLAMA_MODEL,
        "product": selected_product,
        "reasoning": recommendation.reasoning,
        "interpreted_budget": (
            recommendation.interpreted_budget
        ),
        "user_request_summary": (
            recommendation.user_request_summary
        ),
    }


@app.post("/agent/purchase")
async def create_purchase_intent(
    request: ShoppingRequest,
) -> dict:
    """
    Ask the local AI model for a recommendation,
    build a payment intent, sign it and submit it
    to Guardian.
    """

    try:
        (
            recommendation,
            selected_product,
        ) = await recommend(
            request.prompt
        )

    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail=(
                "The local model did not respond "
                "within the configured timeout"
            ),
        ) from exc

    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Unable to communicate with "
                "the local model"
            ),
        ) from exc

    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    current_time = datetime.now(
        timezone.utc
    )

    product_url = selected_product[
        "product_url"
    ]

    merchant_domain = extract_hostname(
        product_url
    )

    price = float(
        selected_product["price"]
    )

    payment_intent = {
        "intent_id": (
            f"INT-{uuid.uuid4().hex[:16]}"
        ),
        "agent_id": AGENT_ID,
        "purpose": "PRODUCT_PURCHASE",
        "merchant": {
            "id": selected_product[
                "platform_merchant_id"
            ],
            "name": selected_product[
                "merchant_name"
            ],
            "category": selected_product[
                "category"
            ],
            "domain": merchant_domain,
            "product_url": product_url,
            "seller_id": selected_product[
                "seller_id"
            ],
        },
        "items": [
            {
                "sku": selected_product[
                    "product_id"
                ],
                "name": selected_product[
                    "name"
                ],
                "quantity": 1,
                "unit_price": price,
            }
        ],
        "currency": "USD",
        "amount": price,
        "purchase_type": selected_product[
            "purchase_type"
        ],
        "nonce": uuid.uuid4().hex,
        "issued_at": utc_isoformat(
            current_time
        ),
        "expires_at": utc_isoformat(
            current_time
            + timedelta(minutes=5)
        ),
    }

    payment_intent["signature"] = (
        sign_payload(
            payment_intent
        )
    )

    try:
        async with httpx.AsyncClient(
            timeout=30.0,
        ) as client:
            response = await client.post(
                (
                    f"{GUARDIAN_API_URL}"
                    "/api/v1/payment-intents"
                ),
                json=payment_intent,
            )

    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail=(
                "Guardian API did not respond "
                "within the configured timeout"
            ),
        ) from exc

    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Unable to connect to Guardian API"
            ),
        ) from exc

    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail=parse_error_response(
                response
            ),
        )

    return {
        "model": OLLAMA_MODEL,
        "product": selected_product,
        "reasoning": recommendation.reasoning,
        "interpreted_budget": (
            recommendation.interpreted_budget
        ),
        "guardian": response.json(),
    }