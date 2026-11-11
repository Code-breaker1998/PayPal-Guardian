import pytest

from app.merchant_trust.engine import evaluate
from app.schemas import Merchant


@pytest.mark.asyncio
async def test_trusted_merchant_is_allowed() -> None:
    merchant = Merchant(
        id="TRUSTED-TECH",
        name="Trusted Tech Store",
        category="ELECTRONICS",
        domain="trusted-tech.example",
        product_url=(
            "https://trusted-tech.example/p/1"
        ),
        seller_id="SELLER-TRUSTED",
    )

    trust_result = await evaluate(
        merchant
    )

    assert trust_result["decision"] == "ALLOW"
    assert trust_result["trust_level"] == "VERIFIED"

    assert (
        "VERIFIED_MERCHANT_AND_SELLER"
        in trust_result["reason_codes"]
    )


@pytest.mark.asyncio
async def test_lookalike_merchant_is_blocked() -> None:
    merchant = Merchant(
        id="AMAZON-FAKE",
        name="Amazon Flash Deals",
        category="ELECTRONICS",
        domain="amaz0n-fast-deals.shop",
        product_url=(
            "https://amaz0n-fast-deals.shop/p/1"
        ),
        seller_id="UNKNOWN",
    )

    trust_result = await evaluate(
        merchant
    )

    assert trust_result["decision"] == "BLOCK"
    assert trust_result["trust_level"] == "HIGH_RISK"

    assert (
        "LOCAL_THREAT_LIST_HIT"
        in trust_result["reason_codes"]
    )

    assert (
        "MERCHANT_NOT_REGISTERED"
        in trust_result["reason_codes"]
    )

    assert (
        "DOMAIN_NOT_REGISTERED"
        in trust_result["reason_codes"]
    )

    assert (
        "BRAND_LOOKALIKE_AMAZON"
        in trust_result["reason_codes"]
    )