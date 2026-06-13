import httpx
from fastapi import APIRouter, HTTPException

from .. import store
from ..agents import orchestrator
from ..config import get_settings
from ..schemas import AgentLogEntry, ApprovalChallenge, Payment, PaymentIntent, Receipt, ReleaseRequest
from ..tools import receipt as receipt_tool

router = APIRouter(prefix="/payments")


@router.post("", response_model=Payment)
async def create_payment(intent: PaymentIntent) -> Payment:
    try:
        return await orchestrator.process_payment(intent)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"FX quote provider rejected {intent.currency}->{get_settings().token_currency}",
        ) from exc
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="FX quote unavailable") from exc


@router.get("", response_model=list[Payment])
async def list_payments() -> list[Payment]:
    return store.list_payments()


@router.get("/{payment_id}", response_model=Payment)
async def get_payment(payment_id: str) -> Payment:
    payment = store.get(payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="payment not found")
    return payment


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
        raise HTTPException(status_code=409, detail="payment is not pending approval") from exc


@router.post("/{payment_id}/release", response_model=Payment)
async def release_payment(payment_id: str, body: ReleaseRequest) -> Payment:
    try:
        return await orchestrator.release_payment(payment_id, body.signature)
    except orchestrator.PaymentNotFound as exc:
        raise HTTPException(status_code=404, detail="payment not found") from exc
    except orchestrator.InvalidApprovalState as exc:
        raise HTTPException(status_code=409, detail="payment is not pending approval") from exc
    except orchestrator.SignatureRejected as exc:
        raise HTTPException(status_code=403, detail="Firefly signature rejected") from exc


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
        raise HTTPException(status_code=403, detail="Firefly signature rejected — payment details were altered")
    # Should never reach here; release_tampered always raises SignatureRejected.
    raise HTTPException(status_code=403, detail="Firefly signature rejected")


@router.get("/{payment_id}/receipt")
async def get_receipt(payment_id: str) -> dict:
    payment = store.get(payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="payment not found")
    if payment.status not in orchestrator.TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="receipt only available for terminal payments")
    r = receipt_tool.build_receipt(payment)
    return {"receipt": r.model_dump(by_alias=True), "receiptHash": payment.receipt_hash}
