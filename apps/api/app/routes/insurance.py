from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..config import get_settings
from ..insurance import binding
from ..insurance import store as insurance_store
from ..schemas import (
    AgentRiskState,
    BindRequest,
    ClaimRequest,
    InsurancePayoutRecord,
    InsurancePremiumRecord,
    InsuranceQuoteRequest,
    PoolStatus,
    PremiumQuote,
)

router = APIRouter(prefix="/insurance")


@router.post("/quote", response_model=PremiumQuote)
async def quote_insurance(request: InsuranceQuoteRequest) -> PremiumQuote:
    _ensure_enabled()
    return await binding.quote(request)


@router.post("/bind", response_model=InsurancePremiumRecord, status_code=201)
async def bind_insurance(request: BindRequest) -> InsurancePremiumRecord:
    _ensure_enabled()
    return await binding.bind(request)


@router.get("/premiums", response_model=list[InsurancePremiumRecord])
async def list_premiums() -> list[InsurancePremiumRecord]:
    return insurance_store.list_premiums()


@router.post("/claim", response_model=InsurancePayoutRecord, status_code=201)
async def settle_claim(request: ClaimRequest) -> InsurancePayoutRecord:
    _ensure_enabled()
    try:
        return await binding.settle_claim(request)
    except binding.ClaimReviewRequired as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except binding.ClaimDeclined as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/payouts", response_model=list[InsurancePayoutRecord])
async def list_payouts() -> list[InsurancePayoutRecord]:
    return insurance_store.list_payouts()


@router.get("/agents/{address}/risk", response_model=AgentRiskState)
async def get_agent_risk(address: str) -> AgentRiskState:
    state = insurance_store.get_agent_risk(address)
    if state is None:
        raise HTTPException(status_code=404, detail="agent risk not found")
    return state


@router.get("/pool", response_model=PoolStatus)
async def get_pool_status() -> PoolStatus:
    return binding.get_pool_status()


def _ensure_enabled() -> None:
    if not get_settings().insurance_enabled:
        raise HTTPException(status_code=403, detail="insurance_enabled is False")

