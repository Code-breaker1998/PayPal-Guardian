import ipaddress
import json
import os
import socket
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup


ALLOWED_REAL_DOMAINS = {
    domain.strip().lower()
    for domain in os.getenv(
        "REAL_WEBSITE_ALLOWLIST",
        "",
    ).split(",")
    if domain.strip()
}

MAX_RESPONSE_BYTES = 2_000_000


def _hostname_allowed(hostname: str) -> bool:
    return any(
        hostname == domain
        or hostname.endswith(f".{domain}")
        for domain in ALLOWED_REAL_DOMAINS
    )


def _assert_public_host(hostname: str) -> None:
    if not ALLOWED_REAL_DOMAINS:
        raise RuntimeError(
            "REAL_WEBSITE_ALLOWLIST is empty"
        )

    if not _hostname_allowed(hostname):
        raise RuntimeError(
            f"Domain {hostname} is not allowlisted"
        )

    try:
        addresses = socket.getaddrinfo(
            hostname,
            443,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise RuntimeError(
            "Website DNS resolution failed"
        ) from exc

    for address in addresses:
        ip_text = address[4][0]
        ip = ipaddress.ip_address(ip_text)

        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise RuntimeError(
                "Website resolves to a non-public IP address"
            )


def validate_real_product_url(url: str) -> tuple[str, str]:
    parsed = urlsplit(url.strip())

    if parsed.scheme.lower() != "https":
        raise RuntimeError(
            "Real product URL must use HTTPS"
        )

    if not parsed.hostname:
        raise RuntimeError(
            "Real product URL has no hostname"
        )

    if parsed.username or parsed.password:
        raise RuntimeError(
            "Embedded URL credentials are not allowed"
        )

    hostname = (
        parsed.hostname
        .rstrip(".")
        .lower()
        .encode("idna")
        .decode("ascii")
    )

    _assert_public_host(hostname)

    normalized_url = parsed.geturl()
    return normalized_url, hostname


def _find_product_node(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        node_type = value.get("@type")
        types = node_type if isinstance(node_type, list) else [node_type]

        if "Product" in types:
            return value

        graph = value.get("@graph")
        if graph is not None:
            result = _find_product_node(graph)
            if result:
                return result

        for child in value.values():
            result = _find_product_node(child)
            if result:
                return result

    if isinstance(value, list):
        for child in value:
            result = _find_product_node(child)
            if result:
                return result

    return None


def _first_offer(product: dict[str, Any]) -> dict[str, Any]:
    offers = product.get("offers")

    if isinstance(offers, list):
        return next(
            (offer for offer in offers if isinstance(offer, dict)),
            {},
        )

    return offers if isinstance(offers, dict) else {}


async def fetch_real_product(url: str) -> dict[str, Any]:
    normalized_url, hostname = validate_real_product_url(url)

    timeout = httpx.Timeout(
        connect=10.0,
        read=20.0,
        write=10.0,
        pool=10.0,
    )

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        headers={
            "User-Agent": (
                "PayPalGuardianHackathon/1.0 "
                "(+controlled-product-verification)"
            ),
            "Accept": "text/html,application/xhtml+xml",
        },
    ) as client:
        response = await client.get(normalized_url)

    if 300 <= response.status_code < 400:
        location = response.headers.get("location")
        if not location:
            raise RuntimeError("Website returned an invalid redirect")

        redirect_url = urljoin(normalized_url, location)
        redirect_url, redirect_host = validate_real_product_url(redirect_url)

        if redirect_host != hostname:
            raise RuntimeError(
                "Cross-domain redirects are not allowed"
            )

        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": "PayPalGuardianHackathon/1.0"},
        ) as client:
            response = await client.get(redirect_url)

        normalized_url = redirect_url

    response.raise_for_status()

    content_type = response.headers.get("content-type", "").lower()
    if "text/html" not in content_type:
        raise RuntimeError(
            "Website did not return HTML"
        )

    if len(response.content) > MAX_RESPONSE_BYTES:
        raise RuntimeError(
            "Website response exceeds the 2 MB safety limit"
        )

    soup = BeautifulSoup(response.text, "html.parser")
    product_node = None

    for script in soup.find_all(
        "script",
        attrs={"type": "application/ld+json"},
    ):
        if not script.string:
            continue

        try:
            data = json.loads(script.string)
        except json.JSONDecodeError:
            continue

        product_node = _find_product_node(data)
        if product_node:
            break

    if not product_node:
        raise RuntimeError(
            "No Schema.org Product JSON-LD was found"
        )

    offer = _first_offer(product_node)
    price = offer.get("price") or offer.get("lowPrice")
    currency = offer.get("priceCurrency", "USD")

    if price is None:
        raise RuntimeError(
            "Product JSON-LD does not contain a price"
        )

    try:
        numeric_price = float(price)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "Product price is not numeric"
        ) from exc

    if numeric_price <= 0:
        raise RuntimeError(
            "Product price must be positive"
        )

    name = str(product_node.get("name", "")).strip()
    if not name:
        raise RuntimeError(
            "Product JSON-LD does not contain a name"
        )

    rating = product_node.get("aggregateRating", {})
    rating_value = None
    if isinstance(rating, dict) and rating.get("ratingValue") is not None:
        try:
            rating_value = float(rating["ratingValue"])
        except (TypeError, ValueError):
            rating_value = None

    product_id = (
        product_node.get("sku")
        or product_node.get("productID")
        or product_node.get("mpn")
        or f"REAL-{hostname}"
    )

    return {
        "product_id": str(product_id),
        "name": name,
        "category": "ELECTRONICS",
        "platform_merchant_id": "REAL-TEST-STORE",
        "merchant_name": hostname,
        "seller_id": "REAL-TEST-SELLER",
        "product_url": normalized_url,
        "price": numeric_price,
        "currency": str(currency).upper(),
        "rating": rating_value or 0.0,
        "features": ["real-website", "live-tls"],
        "purchase_type": "ONE_TIME",
        "source": "SCHEMA_ORG_JSON_LD",
    }
