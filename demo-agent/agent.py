import json
import os
import re
from typing import Any

import httpx
from pydantic import BaseModel, Field

from catalog import PRODUCTS


OLLAMA_BASE_URL = os.getenv(
    "OLLAMA_BASE_URL",
    "http://ollama:11434",
)

OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL",
    "qwen3:0.6b",
)


class Recommendation(BaseModel):
    selected_product_id: str

    reasoning: list[str] = Field(
        min_length=1,
        max_length=5,
    )

    interpreted_budget: float = Field(
        gt=0,
    )

    user_request_summary: str


def get_requested_features(
    prompt: str,
    catalog: list[dict[str, Any]],
) -> set[str]:
    """
    Extract product features explicitly mentioned
    in the user's prompt.

    Only features that exist in the trusted catalog
    are considered.
    """

    normalized_prompt = prompt.lower()

    supported_features = {
        str(feature).strip().lower()
        for product in catalog
        for feature in product.get(
            "features",
            [],
        )
    }

    return {
        feature
        for feature in supported_features
        if feature in normalized_prompt
    }


def extract_budget(
    prompt: str,
) -> float | None:
    """
    Extract a simple numeric budget from prompts such as:

    - under $100
    - below 100
    - budget of $75
    - less than USD 120
    """

    budget_patterns = [
        r"(?:under|below|less\s+than|budget\s+of)"
        r"\s*(?:usd\s*)?\$?\s*(\d+(?:\.\d{1,2})?)",
        r"(?:usd\s*)?\$\s*(\d+(?:\.\d{1,2})?)",
    ]

    normalized_prompt = prompt.lower()

    for pattern in budget_patterns:
        match = re.search(
            pattern,
            normalized_prompt,
        )

        if match:
            return float(
                match.group(1)
            )

    return None


def filter_catalog(
    prompt: str,
    catalog: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Filter products deterministically before sending
    them to the local model.

    Products must satisfy:
    - every explicitly requested feature
    - the user budget, when present
    """

    requested_features = (
        get_requested_features(
            prompt=prompt,
            catalog=catalog,
        )
    )

    requested_budget = extract_budget(
        prompt
    )

    filtered_products: list[
        dict[str, Any]
    ] = []

    for product in catalog:
        product_features = {
            str(feature).strip().lower()
            for feature in product.get(
                "features",
                [],
            )
        }

        features_match = (
            not requested_features
            or requested_features.issubset(
                product_features
            )
        )

        price = float(
            product["price"]
        )

        budget_matches = (
            requested_budget is None
            or price <= requested_budget
        )

        if features_match and budget_matches:
            filtered_products.append(
                product
            )

    return filtered_products


def validate_selected_product(
    prompt: str,
    selected_product: dict[str, Any],
    recommendation: Recommendation,
) -> None:
    """
    Revalidate the local model's selection against
    deterministic catalog constraints.
    """

    validated_products = filter_catalog(
        prompt=prompt,
        catalog=[
            selected_product,
        ],
    )

    if not validated_products:
        raise RuntimeError(
            "The model selected a product that does "
            "not match the requested features or budget"
        )

    product_price = float(
        selected_product["price"]
    )

    if (
        product_price
        > recommendation.interpreted_budget
    ):
        raise RuntimeError(
            "The selected product exceeds the "
            "model-interpreted budget"
        )

    requested_budget = extract_budget(
        prompt
    )

    if (
        requested_budget is not None
        and product_price > requested_budget
    ):
        raise RuntimeError(
            "The selected product exceeds the "
            "budget stated in the user prompt"
        )


async def recommend(
    prompt: str,
) -> tuple[
    Recommendation,
    dict[str, Any],
]:
    """
    Ask the local Ollama model to select one product
    from the deterministically filtered catalog.

    Guardian independently evaluates merchant trust
    after the signed payment intent is submitted.
    """

    safe_catalog = [
        product
        for product in PRODUCTS
        if product[
            "platform_merchant_id"
        ] != "AMAZON-FAKE"
    ]

    if not safe_catalog:
        raise RuntimeError(
            "No safe products are available"
        )

    eligible_catalog = filter_catalog(
        prompt=prompt,
        catalog=safe_catalog,
    )

    if not eligible_catalog:
        requested_features = (
            get_requested_features(
                prompt=prompt,
                catalog=safe_catalog,
            )
        )

        requested_budget = extract_budget(
            prompt
        )

        constraints: list[str] = []

        if requested_features:
            constraints.append(
                "features: "
                + ", ".join(
                    sorted(
                        requested_features
                    )
                )
            )

        if requested_budget is not None:
            constraints.append(
                f"budget: {requested_budget:.2f}"
            )

        constraint_message = (
            "; ".join(constraints)
            if constraints
            else "the supplied request"
        )

        raise RuntimeError(
            "No eligible product matches "
            f"{constraint_message}"
        )

    recommendation_schema = (
        Recommendation.model_json_schema()
    )

    requested_features = (
        get_requested_features(
            prompt=prompt,
            catalog=safe_catalog,
        )
    )

    requested_budget = extract_budget(
        prompt
    )

    request_body = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "think": False,
        "keep_alive": "30m",
        "format": recommendation_schema,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Select exactly one product from "
                    "the supplied eligible catalog. "
                    "The catalog has already been "
                    "filtered using deterministic "
                    "feature and budget checks. "
                    "Never invent a product, merchant, "
                    "price, rating, feature, or product ID. "
                    "Never claim that a product has a "
                    "feature that is not present in its "
                    "features list. "
                    "Prefer the highest-rated eligible "
                    "product unless the user requested "
                    "another ranking criterion. "
                    "Return only JSON matching the "
                    "provided schema."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "request": prompt,
                        "requested_features": sorted(
                            requested_features
                        ),
                        "requested_budget": (
                            requested_budget
                        ),
                        "eligible_catalog": (
                            eligible_catalog
                        ),
                    },
                    ensure_ascii=True,
                ),
            },
        ],
        "options": {
            "temperature": 0,
            "num_ctx": 2048,
            "num_predict": 180,
            "num_thread": 6,
        },
    }

    timeout = httpx.Timeout(
        connect=10.0,
        read=300.0,
        write=30.0,
        pool=10.0,
    )

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
        ) as client:
            response = await client.post(
                (
                    f"{OLLAMA_BASE_URL}"
                    "/api/chat"
                ),
                json=request_body,
            )

        response.raise_for_status()

    except httpx.TimeoutException as exc:
        raise RuntimeError(
            "The local Ollama model did not "
            "respond within the configured timeout"
        ) from exc

    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            "Ollama returned an unsuccessful "
            f"response: {exc.response.status_code}"
        ) from exc

    except httpx.HTTPError as exc:
        raise RuntimeError(
            "Unable to connect to the local "
            "Ollama service"
        ) from exc

    try:
        response_body = response.json()

        recommendation = (
            Recommendation.model_validate_json(
                response_body[
                    "message"
                ][
                    "content"
                ]
            )
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise RuntimeError(
            "The local model returned an invalid "
            "recommendation response"
        ) from exc

    selected_product = next(
        (
            product
            for product in eligible_catalog
            if product["product_id"]
            == recommendation.selected_product_id
        ),
        None,
    )

    if selected_product is None:
        raise RuntimeError(
            "The model selected an unknown, unsafe, "
            "or ineligible product"
        )

    validate_selected_product(
        prompt=prompt,
        selected_product=selected_product,
        recommendation=recommendation,
    )

    return (
        recommendation,
        selected_product,
    )