import httpx
from fastapi import APIRouter, HTTPException, Response

from .. import store
from ..agents import orchestrator
from ..config import get_settings
from ..schemas import (
    AgentLogEntry,
    ApprovalChallenge,
    Payment,
    PaymentIntent,
    QuoteRequest,
    ReleaseRequest,
    RouteQuote,
)
from ..tools import receipt as receipt_tool
from ..tools import receipt_pdf as receipt_pdf_tool
from ..tools import routing

router = APIRouter(prefix="/payments")


@router.post("", response_model=Payment)
async def create_payment(intent: PaymentIntent) -> Payment:
    _validate_destination(intent.to)
    await _validate_destination_exists(intent.to)
    try:
        return _public_payment(await orchestrator.process_payment(intent))
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"FX quote provider rejected {intent.currency}->{get_settings().token_currency}",
        ) from exc
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="FX quote unavailable") from exc
    except Exception as exc:  # never surface a raw 500 (no CORS header) to the browser
        err = str(exc)
        if "tecNO_DST" in err:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Destination account does not exist on XRPL. "
                    "Fund it on the configured XRPL network first."
                ),
            ) from exc
        raise HTTPException(
            status_code=502, detail=f"Payment processing failed: {exc}"
        ) from exc


@router.post("/quote", response_model=RouteQuote)
async def quote_payment(request: QuoteRequest) -> RouteQuote:
    try:
        return await routing.quote_amount(
            request.amount, request.currency, get_settings().token_currency
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Quote provider rejected {request.currency}->{get_settings().token_currency}",
        ) from exc
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Quote unavailable") from exc


@router.get("", response_model=list[Payment])
async def list_payments() -> list[Payment]:
    return [_public_payment(payment) for payment in store.list_payments()]


@router.get("/{payment_id}", response_model=Payment)
async def get_payment(payment_id: str) -> Payment:
    payment = store.get(payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="payment not found")
    return _public_payment(payment)


@router.get("/{payment_id}/logs", response_model=list[AgentLogEntry])
async def get_logs(payment_id: str) -> list[AgentLogEntry]:
    return store.logs_for(payment_id)


@router.get("/{payment_id}/challenge", response_model=ApprovalChallenge)
async def get_challenge(payment_id: str) -> ApprovalChallenge:
    try:
        return orchestrator.challenge_for(payment_id)
    except orchestrator.PaymentNotFound as exc:
        raise HTTPException(status_code=404, detail="payment not found") from exc
    except orchestrator.InvalidApprovalState as exc:
        raise HTTPException(
            status_code=409, detail="payment is not pending approval"
        ) from exc


@router.post("/{payment_id}/release", response_model=Payment)
async def release_payment(payment_id: str, body: ReleaseRequest) -> Payment:
    try:
        return _public_payment(
            await orchestrator.release_payment(payment_id, body.signature)
        )
    except orchestrator.PaymentNotFound as exc:
        raise HTTPException(status_code=404, detail="payment not found") from exc
    except orchestrator.InvalidApprovalState as exc:
        raise HTTPException(
            status_code=409, detail="payment is not pending approval"
        ) from exc
    except orchestrator.SignatureRejected as exc:
        raise HTTPException(
            status_code=403, detail="Firefly signature rejected"
        ) from exc


@router.post("/{payment_id}/release-tampered", status_code=403)
async def release_tampered(payment_id: str, body: ReleaseRequest) -> dict:
    """DEMO ONLY. Proves signature binding by verifying against a tampered copy.

    Always returns 403 — the point is to show the signature doesn't verify
    when payment details are altered. Requires DEMO_MODE=true.
    """
    if not get_settings().demo_mode:
        raise HTTPException(status_code=404, detail="not found")
    try:
        await orchestrator.release_tampered(payment_id, body.signature)
    except orchestrator.PaymentNotFound as exc:
        raise HTTPException(status_code=404, detail="payment not found") from exc
    except orchestrator.SignatureRejected:
        raise HTTPException(
            status_code=403,
            detail="Firefly signature rejected — payment details were altered",
        )
    # Should never reach here; release_tampered always raises SignatureRejected.
    raise HTTPException(status_code=403, detail="Firefly signature rejected")


@router.get("/{payment_id}/receipt")
async def get_receipt(payment_id: str) -> dict:
    payment = store.get(payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="payment not found")
    if payment.status not in orchestrator.TERMINAL_STATUSES:
        raise HTTPException(
            status_code=409, detail="receipt only available for terminal payments"
        )
    r = receipt_tool.build_receipt(payment)
    return {"receipt": r.model_dump(by_alias=True), "receiptHash": payment.receipt_hash}


@router.get("/{payment_id}/receipt.pdf")
async def get_receipt_pdf(payment_id: str) -> Response:
    payment = store.get(payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="payment not found")
    if payment.status not in orchestrator.TERMINAL_STATUSES:
        raise HTTPException(
            status_code=409, detail="receipt only available for terminal payments"
        )
    pdf = receipt_pdf_tool.build_receipt_pdf(payment)
    filename = f"audit-report-{payment.id[:8]}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _validate_destination(address: str) -> None:
    """Reject an invalid XRPL destination up front.

    The orchestrator builds a Payment/EscrowCreate from this address; an invalid
    one makes xrpl-py raise deep in serialization, surfacing as a 500 with no
    CORS header. A 422 here returns a clean, CORS-headed message instead.
    """
    from xrpl.core.addresscodec import is_valid_classic_address, is_valid_xaddress

    try:
        valid = is_valid_classic_address(address) or is_valid_xaddress(address)
    except Exception:
        valid = False
    if not valid:
        raise HTTPException(
            status_code=422, detail=f"Invalid destination XRPL address: {address!r}"
        )


async def _validate_destination_exists(address: str) -> None:
    """Fail before signing when a destination is absent on the active network."""
    settings = get_settings()
    from xrpl.models.requests import AccountInfo
    from .. import xrpl_client

    try:
        async with xrpl_client.async_client(settings.xrpl_endpoint) as client:
            response = await client.request(
                AccountInfo(account=address, ledger_index="validated")
            )
    except Exception as exc:
        # Connectivity failures are handled by the normal transaction path; do
        # not turn a best-effort preflight into a new availability dependency.
        if "actNotFound" in str(exc):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Destination account does not exist on the configured XRPL network. "
                    "Use an account funded on that same network."
                ),
            ) from exc
        return
    if not response.is_successful() or response.result.get("error") in (
        "actNotFound",
        "actMalformed",
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Destination account does not exist on the configured XRPL network. "
                "Fund it on that same network before retrying."
            ),
        )


def _public_payment(payment: Payment) -> Payment:
    return payment
