from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from real_website import fetch_real_product


router = APIRouter(prefix="/agent/real-site", tags=["Real Website Test"])


class RealWebsiteRequest(BaseModel):
    product_url: str = Field(min_length=12, max_length=2000)


@router.post("/inspect")
async def inspect_real_website(
    request: RealWebsiteRequest,
) -> dict:
    try:
        product = await fetch_real_product(
            request.product_url
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Real website inspection failed",
        ) from exc

    return {
        "status": "VERIFIED_FOR_DEMO",
        "product": product,
        "next_step": (
            "Add REAL-TEST-STORE to Guardian merchant registry "
            "and submit the product through the signed-intent flow."
        ),
    }
