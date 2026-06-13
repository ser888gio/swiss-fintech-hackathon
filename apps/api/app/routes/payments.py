from fastapi import APIRouter, HTTPException

from .. import store
from ..agents import orchestrator
from ..schemas import AgentLogEntry, ApprovalChallenge, Payment, PaymentIntent, ReleaseRequest

router = APIRouter(prefix="/payments")


@router.post("", response_model=Payment)
async def create_payment(intent: PaymentIntent) -> Payment:
    return await orchestrator.process_payment(intent)


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
