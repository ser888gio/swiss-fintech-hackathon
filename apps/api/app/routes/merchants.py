"""Simulated Maersk counterparties hosted inside the existing API service."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from ..config import get_settings
from ..tools import x402

router = APIRouter(prefix="/merchants", tags=["merchants"])


@router.get("/{slug}", name="merchant_resource")
async def merchant_resource(
    slug: str,
    request: Request,
    price: str | None = Query(default=None),
):
    if slug not in x402._MERCHANTS:
        raise HTTPException(status_code=404, detail="merchant not found")
    settings = get_settings()
    proof = request.headers.get("X-PAYMENT")
    if not proof:
        # Only the repair demo accepts an explicit over-threshold scenario.
        override = price if slug == "repair-yard" and price == "4.000000" else None
        try:
            requirement = x402.issue_merchant_requirement(
                slug, str(request.url), settings, price_override=override
            )
        except x402.X402Error as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        return JSONResponse(
            status_code=402,
            content={
                "payTo": requirement.pay_to,
                "currency": requirement.asset_currency,
                "issuer": requirement.asset_issuer,
                "network": requirement.network,
                "amount": requirement.amount,
                "invoiceId": requirement.invoice_id,
                "sourceTag": requirement.source_tag,
                "facilitatorUrl": requirement.facilitator_url,
            },
        )
    try:
        tx_hash = await x402.verify_merchant_proof(proof, slug, settings)
    except x402.X402Error as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    return {
        "status": "invoice settled",
        "merchant": slug,
        "txHash": tx_hash,
    }
