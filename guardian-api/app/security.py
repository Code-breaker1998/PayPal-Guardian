import base64
import hashlib
import json
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PublicKey,
)

from .schemas import PaymentIntentCreate


def utc_isoformat(
    value: datetime,
) -> str:
    return (
        value
        .astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def canonical_payload(
    payment_intent: PaymentIntentCreate,
) -> bytes:
    intent_data = payment_intent.model_dump(
        mode="json",
        exclude={"signature"},
    )

    intent_data["issued_at"] = utc_isoformat(
        payment_intent.issued_at
    )

    intent_data["expires_at"] = utc_isoformat(
        payment_intent.expires_at
    )

    intent_data["currency"] = (
        payment_intent.currency.upper()
    )

    canonical_json = json.dumps(
        intent_data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )

    return canonical_json.encode("utf-8")


def calculate_payload_hash(
    payment_intent: PaymentIntentCreate,
) -> str:
    return hashlib.sha256(
        canonical_payload(payment_intent)
    ).hexdigest()


def verify_signature(
    public_key_pem: str,
    payment_intent: PaymentIntentCreate,
) -> bool:
    try:
        public_key = (
            serialization.load_pem_public_key(
                public_key_pem.encode("utf-8")
            )
        )

        if not isinstance(
            public_key,
            Ed25519PublicKey,
        ):
            return False

        decoded_signature = base64.b64decode(
            payment_intent.signature,
            validate=True,
        )

        public_key.verify(
            decoded_signature,
            canonical_payload(payment_intent),
        )

        return True

    except (
        ValueError,
        TypeError,
        InvalidSignature,
    ):
        return False


def assert_time_valid(
    payment_intent: PaymentIntentCreate,
) -> None:
    current_time = datetime.now(
        timezone.utc
    )

    future_time_difference = (
        payment_intent.issued_at
        - current_time
    ).total_seconds()

    if future_time_difference > 30:
        raise ValueError(
            "intent issued_at is too far in future"
        )

    if current_time > payment_intent.expires_at:
        raise ValueError(
            "intent has expired"
        )