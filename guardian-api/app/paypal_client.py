import os
import uuid
from typing import Any

import httpx

PAYPAL_BASE_URL = os.getenv(
    "PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com"
)
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "")
PAYPAL_RETURN_URL = os.getenv(
    "PAYPAL_RETURN_URL", "http://localhost:3000/paypal/return"
)
PAYPAL_CANCEL_URL = os.getenv(
    "PAYPAL_CANCEL_URL", "http://localhost:3000/paypal/cancel"
)


class PayPalConfigurationError(RuntimeError):
    pass


class PayPalAPIError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _assert_configured() -> None:
    if not PAYPAL_CLIENT_ID or not PAYPAL_CLIENT_SECRET:
        raise PayPalConfigurationError(
            "PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET are required"
        )


async def get_access_token() -> str:
    _assert_configured()
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{PAYPAL_BASE_URL}/v1/oauth2/token",
            auth=(PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET),
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json"},
        )
    if response.status_code >= 400:
        raise PayPalAPIError(response.status_code, response.text)
    return response.json()["access_token"]


async def create_order(
    *,
    intent_id: str,
    amount: str,
    currency: str,
    description: str,
) -> dict[str, Any]:
    access_token = await get_access_token()
    request_id = f"guardian-create-{intent_id}-{uuid.uuid4().hex[:8]}"
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "reference_id": intent_id,
                "description": description[:127],
                "amount": {
                    "currency_code": currency.upper(),
                    "value": amount,
                },
            }
        ],
        "payment_source": {
            "paypal": {
                "experience_context": {
                    "brand_name": "PayPal Guardian",
                    "user_action": "PAY_NOW",
                    "return_url": PAYPAL_RETURN_URL,
                    "cancel_url": PAYPAL_CANCEL_URL,
                }
            }
        },
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{PAYPAL_BASE_URL}/v2/checkout/orders",
            json=payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "PayPal-Request-Id": request_id,
                "Prefer": "return=representation",
            },
        )
    if response.status_code >= 400:
        raise PayPalAPIError(response.status_code, response.text)
    return response.json()


async def capture_order(order_id: str) -> dict[str, Any]:
    access_token = await get_access_token()
    request_id = f"guardian-capture-{order_id}-{uuid.uuid4().hex[:8]}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{PAYPAL_BASE_URL}/v2/checkout/orders/{order_id}/capture",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "PayPal-Request-Id": request_id,
                "Prefer": "return=representation",
            },
        )
    if response.status_code >= 400:
        raise PayPalAPIError(response.status_code, response.text)
    return response.json()
