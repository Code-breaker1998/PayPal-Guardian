import asyncio
import hashlib
import json
import socket
import ssl
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit


MERCHANT_REGISTRY = {
    "TRUSTED-TECH": {
        "domain": "trusted-tech.example",
        "seller": "SELLER-TRUSTED",
        "seller_status": "KNOWN",
        "tls_mode": "DEMO_ASSERTED",
    },
    "KEYBOARD-MARKET": {
        "domain": "keyboard-market.example",
        "seller": "SELLER-NEW",
        "seller_status": "NEW",
        "tls_mode": "DEMO_ASSERTED",
    },
}


LOCAL_DOMAIN_BLOCKLIST = {
    "amaz0n-fast-deals.shop",
    "paypa1-security.example",
}


KNOWN_BRAND_DOMAINS = {
    "amazon": "amazon.in",
    "paypal": "paypal.com",
    "ebay": "ebay.com",
}


LOOKALIKE_CHARACTER_MAP = str.maketrans(
    {
        "0": "o",
        "1": "l",
        "3": "e",
    }
)


def domain_matches(
    hostname: str,
    registered_domain: str,
) -> bool:
    """
    Check whether the hostname is exactly the registered
    domain or one of its subdomains.
    """

    return (
        hostname == registered_domain
        or hostname.endswith(
            f".{registered_domain}"
        )
    )


def normalize_url(
    url: str,
) -> tuple[str, int]:
    """
    Validate and normalize a merchant URL.

    Returns:
        A tuple containing normalized hostname and port.

    Raises:
        ValueError: If the URL does not satisfy security rules.
    """

    parsed_url = urlsplit(
        url.strip()
    )

    if parsed_url.scheme.lower() != "https":
        raise ValueError(
            "HTTPS_REQUIRED"
        )

    if not parsed_url.hostname:
        raise ValueError(
            "INVALID_HOSTNAME"
        )

    if parsed_url.username or parsed_url.password:
        raise ValueError(
            "EMBEDDED_CREDENTIALS_NOT_ALLOWED"
        )

    normalized_hostname = (
        parsed_url.hostname
        .rstrip(".")
        .lower()
    )

    try:
        normalized_hostname = (
            normalized_hostname
            .encode("idna")
            .decode("ascii")
        )
    except UnicodeError as exc:
        raise ValueError(
            "INVALID_IDN_HOSTNAME"
        ) from exc

    port = parsed_url.port or 443

    return normalized_hostname, port


def validate_tls_certificate_sync(
    hostname: str,
    port: int,
) -> dict[str, Any]:
    """
    Perform synchronous TLS certificate validation.

    ssl.create_default_context() verifies:
    - certificate chain
    - certificate validity
    - hostname matching
    - trusted certificate authority
    """

    ssl_context = ssl.create_default_context()

    try:
        with socket.create_connection(
            (hostname, port),
            timeout=5.0,
        ) as tcp_socket:
            with ssl_context.wrap_socket(
                tcp_socket,
                server_hostname=hostname,
            ) as tls_socket:
                certificate = (
                    tls_socket.getpeercert()
                )

        return {
            "valid": True,
            "hostname_match": True,
            "chain_trusted": True,
            "expires_at": certificate.get(
                "notAfter"
            ),
            "issuer": str(
                certificate.get("issuer")
            ),
            "error": None,
            "mode": "LIVE",
        }

    except ssl.SSLCertVerificationError as exc:
        return {
            "valid": False,
            "hostname_match": False,
            "chain_trusted": False,
            "expires_at": None,
            "issuer": None,
            "error": (
                "TLS_CERTIFICATE_INVALID: "
                f"{exc.verify_message}"
            ),
            "mode": "LIVE",
        }

    except socket.timeout:
        return {
            "valid": False,
            "hostname_match": False,
            "chain_trusted": False,
            "expires_at": None,
            "issuer": None,
            "error": "TLS_CONNECTION_TIMEOUT",
            "mode": "LIVE",
        }

    except (
        ssl.SSLError,
        socket.gaierror,
        ConnectionError,
        OSError,
    ) as exc:
        return {
            "valid": False,
            "hostname_match": False,
            "chain_trusted": False,
            "expires_at": None,
            "issuer": None,
            "error": (
                "TLS_CONNECTION_FAILED: "
                f"{type(exc).__name__}"
            ),
            "mode": "LIVE",
        }


async def validate_tls_certificate(
    hostname: str,
    port: int,
) -> dict[str, Any]:
    """
    Run blocking TLS validation in a worker thread
    so that the FastAPI event loop remains responsive.
    """

    return await asyncio.to_thread(
        validate_tls_certificate_sync,
        hostname,
        port,
    )


def detect_lookalike_domain(
    hostname: str,
    registered_domain: str | None,
) -> list[str]:
    """
    Detect basic brand-lookalike and Punycode signals.
    """

    reason_codes: list[str] = []

    if (
        hostname.startswith("xn--")
        or ".xn--" in hostname
    ):
        reason_codes.append(
            "PUNYCODE_DOMAIN"
        )

    hostname_label = (
        hostname
        .split(".")[0]
        .replace("-", "")
        .translate(
            LOOKALIKE_CHARACTER_MAP
        )
    )

    for (
        brand_name,
        official_domain,
    ) in KNOWN_BRAND_DOMAINS.items():
        if registered_domain == official_domain:
            continue

        if brand_name in hostname_label:
            reason_codes.append(
                "BRAND_LOOKALIKE_"
                f"{brand_name.upper()}"
            )

    return sorted(
        set(reason_codes)
    )


async def evaluate(
    product: dict[str, Any],
) -> dict[str, Any]:
    """
    Evaluate merchant, domain, TLS certificate and seller trust.
    """

    evidence_id = (
        f"MTE-{uuid.uuid4().hex[:16]}"
    )

    reason_codes: list[str] = []
    trust_score = 0

    product_url = product["product_url"]
    merchant_id = product[
        "platform_merchant_id"
    ]
    seller_id = product["seller_id"]

    try:
        (
            normalized_hostname,
            port,
        ) = normalize_url(product_url)

    except ValueError as exc:
        return build_trust_result(
            evidence_id=evidence_id,
            product=product,
            normalized_hostname=None,
            registered_domain=None,
            tls_result={
                "valid": False,
                "hostname_match": False,
                "chain_trusted": False,
                "error": str(exc),
                "mode": "NOT_EVALUATED",
            },
            seller_status="UNKNOWN",
            trust
            trust_level="HIGH_RISK",
            decision="BLOCK",
            reason_codes=[
                str(exc)
            ],
        )

    merchant = MERCHANT_REGISTRY.get(
        merchant_id
    )

    registered_domain = (
        merchant["domain"]
        if merchant
        else None
    )

    if (
        normalized_hostname
        in LOCAL_DOMAIN_BLOCKLIST
    ):
        reason_codes.append(
            "LOCAL_THREAT_LIST_HIT"
        )
        trust_score += 100

    if merchant is None:
        reason_codes.append(
            "MERCHANT_NOT_REGISTERED"
        )
        trust_score += 80

    domain_verified = bool(
        registered_domain
        and domain_matches(
            normalized_hostname,
            registered_domain,
        )
    )

    if not domain_verified:
        reason_codes.append(
            "DOMAIN_NOT_REGISTERED"
        )
        trust_score += 60

    lookalike_reasons = (
        detect_lookalike_domain(
            hostname=normalized_hostname,
            registered_domain=registered_domain,
        )
    )

    reason_codes.extend(
        lookalike_reasons
    )

    if any(
        reason.startswith(
            "BRAND_LOOKALIKE_"
        )
        or reason == "PUNYCODE_DOMAIN"
        for reason in lookalike_reasons
    ):
        trust_score += 40

    if (
        merchant
        and merchant.get("tls_mode")
        == "DEMO_ASSERTED"
        and domain_verified
    ):
        tls_result = {
            "valid": True,
            "hostname_match": True,
            "chain_trusted": True,
            "expires_at": None,
            "issuer": (
                "LOCAL_DEMO_REGISTRY"
            ),
            "error": None,
            "mode": "DEMO_ASSERTED",
        }

    else:
        tls_result = (
            await validate_tls_certificate(
                hostname=normalized_hostname,
                port=port,
            )
        )

    if not tls_result["valid"]:
        reason_codes.append(
            "TLS_VALIDATION_FAILED"
        )
        trust_score += 60

    seller_status = "UNKNOWN"

    if (
        merchant
        and seller_id
        == merchant["seller"]
    ):
        seller_status = merchant[
            "seller_status"
        ]

    if seller_status == "NEW":
        reason_codes.append(
            "NEW_MARKETPLACE_SELLER"
        )
        trust_score += 30

    elif seller_status == "UNKNOWN":
        reason_codes.append(
            "UNKNOWN_SELLER"
        )
        trust_score += 50

    hard_block_reasons = {
        "LOCAL_THREAT_LIST_HIT",
        "MERCHANT_NOT_REGISTERED",
        "DOMAIN_NOT_REGISTERED",
        "TLS_VALIDATION_FAILED",
    }

    has_hard_block = bool(
        hard_block_reasons.intersection(
            reason_codes
        )
    )

    has_brand_lookalike = any(
        reason.startswith(
            "BRAND_LOOKALIKE_"
        )
        for reason in reason_codes
    )

    if has_hard_block or has_brand_lookalike:
        decision = "BLOCK"
        trust_level = "HIGH_RISK"

    elif seller_status != "KNOWN":
        decision = "REVIEW"
        trust_level = "MEDIUM"

    else:
        decision = "ALLOW"
        trust_level = "VERIFIED"

        reason_codes.append(
            "VERIFIED_MERCHANT_AND_SELLER"
        )

    return build_trust_result(
        evidence_id=evidence_id,
        product=product,
        normalized_hostname=(
            normalized_hostname
        ),
        registered_domain=registered_domain,
        tls_result=tls_result,
        seller_status=seller_status,
        trust_score=min(
            trust_score,
            100,
        ),
        trust_level=trust_level,
        decision=decision,
        reason_codes=sorted(
            set(reason_codes)
        ),
    )


def build_trust_result(
    evidence_id: str,
    product: dict[str, Any],
    normalized_hostname: str | None,
    registered_domain: str | None,
    tls_result: dict[str, Any],
    seller_status: str,
    trust_score: int,
    trust_level: str,
    decision: str,
    reason_codes: list[str],
) -> dict[str, Any]:
    """
    Build immutable-style trust evidence and generate
    its deterministic SHA-256 fingerprint.
    """

    trust_evidence = {
        "evidence_id": evidence_id,
        "evaluated_at": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
        "submitted_url": product[
            "product_url"
        ],
        "normalized_hostname": (
            normalized_hostname
        ),
        "registered_domain": (
            registered_domain
        ),
        "merchant_id": product[
            "platform_merchant_id"
        ],
        "seller_id": product[
            "seller_id"
        ],
        "tls": tls_result,
        "seller_status": seller_status,
        "trust_score": trust_score,
        "trust_level": trust_level,
        "decision": decision,
        "reason_codes": reason_codes,
    }

    canonical_evidence = json.dumps(
        trust_evidence,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")

    trust_evidence["evidence_hash"] = (
        hashlib.sha256(
            canonical_evidence
        ).hexdigest()
    )

    return trust_evidence