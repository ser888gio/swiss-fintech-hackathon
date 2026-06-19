"""Autonomous treasury agent endpoints."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from ..agents import orchestrator, treasury_agent
from ..config import get_settings
from ..schemas import (
    DelegationGrant,
    DelegationGrantCreate,
    MPTAttestationRecord,
    MPTAuthorizeRequest,
    MPTStatus,
    Receivable,
    ReceivableCreate,
    TreasuryAgentRun,
    TreasuryGoal,
    TreasuryGoalCreate,
    VaultDepositRequest,
    VaultOpRecord,
    VaultStatus,
    VaultWithdrawRequest,
    X402Settlement,
)
from .. import xrpl_client
from ..tools import delegation as delegation_tool
from ..tools import mptoken as mptoken_tool
from ..tools import trade_finance as tf_tool
from ..tools import vault as vault_tool

router = APIRouter(prefix="/treasury")


@router.post("/goals", response_model=TreasuryGoal, status_code=201)
async def create_goal(request: TreasuryGoalCreate) -> TreasuryGoal:
    goal = treasury_agent.goal_from_create(request)
    return treasury_agent.add_goal(goal)


@router.get("/goals", response_model=list[TreasuryGoal])
async def list_goals() -> list[TreasuryGoal]:
    return treasury_agent.list_goals()


@router.get("/goals/{goal_id}", response_model=TreasuryGoal)
async def get_goal(goal_id: str) -> TreasuryGoal:
    goal = treasury_agent.get_goal(goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="goal not found")
    return goal


@router.delete("/goals/{goal_id}", status_code=204)
async def delete_goal(goal_id: str) -> None:
    if not treasury_agent.remove_goal(goal_id):
        raise HTTPException(status_code=404, detail="goal not found")


@router.post("/run", response_model=TreasuryAgentRun)
async def trigger_run() -> TreasuryAgentRun:
    """Trigger one evaluation cycle immediately.

    In production this would be called by a scheduler (cron / Railway cron job).
    The demo calls it explicitly so the cycle is visible in the UI.
    """
    if not get_settings().agent_enabled:
        raise HTTPException(status_code=403, detail="autonomous agent is disabled (AGENT_ENABLED=false)")
    return await treasury_agent.run()


@router.get("/runs", response_model=list[TreasuryAgentRun])
async def list_runs() -> list[TreasuryAgentRun]:
    return treasury_agent.list_runs()


@router.get("/vault", response_model=VaultStatus)
async def get_vault_status() -> VaultStatus:
    """Return the current vault position and configuration."""
    settings = get_settings()
    state = vault_tool.get_vault_state()
    network = xrpl_client.network_label(settings.vault_xrpl_endpoint, use_mock=settings.use_mock_xrpl)
    return VaultStatus(
        vault_id=settings.vault_id or state["vault_id"],
        enabled=settings.vault_enabled,
        network=network,
        deposited=state["deposited"],
        shares=state["shares"],
        wallet_balance=state["wallet_balance"],
        asset_currency=settings.token_currency,
        asset_issuer=settings.token_issuer_address or None,
        sweep_threshold_usd=settings.vault_sweep_threshold_usd,
        recall_threshold_usd=settings.vault_recall_threshold_usd,
        recent_operations=_recent_vault_records(state["operations"]),
    )


@router.post("/vault", response_model=VaultOpRecord, status_code=201)
async def create_vault() -> VaultOpRecord:
    """VaultCreate: provision a Single Asset Vault for the treasury token.

    In mock mode this is instantaneous. In real mode it submits a VaultCreate
    tx on the vault network (Devnet by default). The returned vault_id should
    be stored in VAULT_ID for subsequent deposit/withdraw calls.
    """
    settings = get_settings()
    result = await vault_tool.create_vault(
        asset_currency=settings.token_currency,
        asset_issuer=settings.token_issuer_address or "rMOCK_ISSUER",
    )
    return _vault_record(
        id=result.vault_id[:8],
        operation="create",
        amount=0.0,
        tx_hash=result.tx_hash,
        explorer_url=result.explorer_url,
        timestamp=datetime.now(timezone.utc),
    )


@router.post("/vault/deposit", response_model=VaultOpRecord, status_code=201)
async def deposit_to_vault(request: VaultDepositRequest) -> VaultOpRecord:
    """VaultDeposit: sweep the given amount into the vault to earn yield."""
    vault_id = _current_vault_id()
    result = await vault_tool.deposit(vault_id, request.amount)
    return _vault_record(
        operation="deposit",
        amount=result.amount,
        tx_hash=result.tx_hash,
        explorer_url=result.explorer_url,
        timestamp=result.timestamp,
    )


@router.post("/vault/withdraw", response_model=VaultOpRecord, status_code=201)
async def withdraw_from_vault(request: VaultWithdrawRequest) -> VaultOpRecord:
    """VaultWithdraw: recall the given amount from the vault back to the treasury."""
    vault_id = _current_vault_id()
    result = await vault_tool.withdraw(vault_id, request.amount)
    return _vault_record(
        operation="withdraw",
        amount=result.amount,
        tx_hash=result.tx_hash,
        explorer_url=result.explorer_url,
        timestamp=result.timestamp,
    )


@router.get("/mpt", response_model=MPTStatus)
async def get_mpt_status() -> MPTStatus:
    """Return the COMPLY issuance state and recent attestation audit trail."""
    settings = get_settings()
    state = mptoken_tool.get_mpt_state()
    network = xrpl_client.network_label(
        settings.mpt_xrpl_endpoint or settings.xrpl_endpoint, use_mock=settings.use_mock_xrpl
    )
    return MPTStatus(
        issuance_id=settings.mpt_issuance_id or state["issuance_id"],
        enabled=settings.mpt_enabled,
        network=network,
        metadata_hex=mptoken_tool.COMPLY_METADATA,
        total_minted=state["total_minted"],
        authorized_count=len(state["authorized"]),
        recent_attestations=_recent_mpt_records(state["attestations"]),
    )


@router.post("/mpt/issuance", response_model=MPTStatus, status_code=201)
async def create_mpt_issuance() -> MPTStatus:
    """MPTokenIssuanceCreate: provision the COMPLY compliance-attestation issuance.

    In mock mode this is instantaneous. In real mode it submits a
    MPTokenIssuanceCreate tx on the configured network (Testnet by default).
    The returned issuance_id should be stored in MPT_ISSUANCE_ID.
    """
    await mptoken_tool.create_issuance()
    # Delegate to get_mpt_status so the response shape is always consistent.
    return await get_mpt_status()


@router.post("/mpt/authorize", response_model=MPTAttestationRecord, status_code=201)
async def authorize_mpt_holder(request: MPTAuthorizeRequest) -> MPTAttestationRecord:
    """MPTokenAuthorize: authorize an address to receive COMPLY attestation tokens.

    In mock mode adds the holder to the in-memory authorized list.
    In real mode submits MPTokenAuthorize from the treasury account.
    """
    result = await mptoken_tool.authorize_holder(_current_mpt_issuance_id(), request.holder)
    return _mpt_record(result, payment_id="", amount_settled=0.0)


@router.post("/mpt/mint", response_model=MPTAttestationRecord, status_code=201)
async def mint_mpt_attestation() -> MPTAttestationRecord:
    """Mint 1 COMPLY token: manual trigger for dashboard testing.

    Useful for testing the flow from the dashboard without waiting for an
    agent cycle to complete.
    """
    settings = get_settings()
    payment_id = "manual"
    amount_settled = 0.0
    result = await mptoken_tool.mint_attestation(
        issuance_id=_current_mpt_issuance_id(),
        recipient=settings.mpt_recipient_address or "rDEMO_RECIPIENT",
        payment_id=payment_id,
        amount_settled=amount_settled,
    )
    return _mpt_record(result, payment_id=payment_id, amount_settled=amount_settled)


# ── Trade Finance / On-chain Credit ──────────────────────────────────────────

@router.post("/receivables", response_model=Receivable, status_code=201)
async def register_receivable(create: ReceivableCreate) -> Receivable:
    """Register a trade-finance receivable (supplier early-payment claim)."""
    settings = get_settings()
    if not settings.trade_finance_enabled:
        raise HTTPException(status_code=403, detail="trade_finance_enabled is False")
    return await orchestrator.register_receivable(create)


@router.get("/receivables", response_model=list[Receivable])
async def list_receivables() -> list[Receivable]:
    return tf_tool.list_receivables()


@router.get("/receivables/{invoice_id}", response_model=Receivable)
async def get_receivable(invoice_id: str) -> Receivable:
    rec = tf_tool.get_by_invoice(invoice_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="receivable not found")
    return rec


@router.post("/receivables/{invoice_id}/pay-early", response_model=Receivable)
async def pay_supplier_early(invoice_id: str) -> Receivable:
    """Draw from the vault pool, pay the supplier at a discount. Runs G1+G4+G6."""
    settings = get_settings()
    if not settings.trade_finance_enabled:
        raise HTTPException(status_code=403, detail="trade_finance_enabled is False")
    try:
        return await orchestrator.process_early_payment(invoice_id)
    except orchestrator.GuardrailBlocked as exc:
        raise HTTPException(status_code=403, detail=f"Guardrail {exc.guardrail} blocked: {exc.reason}")
    except orchestrator.GuardrailEscalation as exc:
        raise HTTPException(status_code=402, detail=f"Requires hardware approval: {exc.reason}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/receivables/{invoice_id}/collect", response_model=Receivable)
async def collect_repayment(invoice_id: str) -> Receivable:
    """Record buyer repayment and replenish the vault pool."""
    settings = get_settings()
    if not settings.trade_finance_enabled:
        raise HTTPException(status_code=403, detail="trade_finance_enabled is False")
    try:
        return await orchestrator.collect_repayment(invoice_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# ── x402 Service Payments ─────────────────────────────────────────────────────

from pydantic import BaseModel

class ServicePaymentRequest(BaseModel):
    service_url: str
    service_type: str = "data_lookup"


@router.post("/service-payment", response_model=X402Settlement, status_code=201)
async def trigger_service_payment(req: ServicePaymentRequest) -> X402Settlement:
    """Pay for an external service via x402 (G1+G4 guardrailed)."""
    settings = get_settings()
    if not settings.x402_enabled:
        raise HTTPException(status_code=403, detail="x402_enabled is False")
    try:
        result = await orchestrator.process_service_payment(
            req.service_url, service_type=req.service_type
        )
        return result.payment
    except orchestrator.GuardrailBlocked as exc:
        raise HTTPException(status_code=403, detail=f"Guardrail {exc.guardrail} blocked: {exc.reason}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# ── Delegation ────────────────────────────────────────────────────────────────

@router.post("/delegations", response_model=DelegationGrant, status_code=201)
async def create_delegation(create: DelegationGrantCreate) -> DelegationGrant:
    """Grant a scoped budget to a sub-agent wallet (G1 guardrailed)."""
    settings = get_settings()
    if not settings.delegation_enabled:
        raise HTTPException(status_code=403, detail="delegation_enabled is False")
    try:
        return await orchestrator.process_delegation_fund(create)
    except orchestrator.GuardrailBlocked as exc:
        raise HTTPException(status_code=403, detail=f"Guardrail {exc.guardrail} blocked: {exc.reason}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/delegations", response_model=list[DelegationGrant])
async def list_delegations() -> list[DelegationGrant]:
    from ..tools.delegation import _grants
    return list(_grants.values())


@router.delete("/delegations/{grant_id}", response_model=DelegationGrant)
async def revoke_delegation(grant_id: str) -> DelegationGrant:
    try:
        return delegation_tool.revoke_delegation(grant_id)
    except delegation_tool.DelegationNotFound:
        raise HTTPException(status_code=404, detail="grant not found")


def _current_vault_id() -> str:
    vault_id = get_settings().vault_id or vault_tool.get_vault_state().get("vault_id")
    if not vault_id:
        raise HTTPException(
            status_code=409,
            detail="No vault exists yet. Call POST /treasury/vault to create one first.",
        )
    return vault_id


def _current_mpt_issuance_id() -> str:
    issuance_id = get_settings().mpt_issuance_id or mptoken_tool.get_mpt_state().get("issuance_id")
    if not issuance_id:
        raise HTTPException(
            status_code=409,
            detail="No MPT issuance yet. Call POST /treasury/mpt/issuance first.",
        )
    return issuance_id


def _vault_record(
    *,
    operation: str,
    amount: float,
    tx_hash: str,
    explorer_url: str | None,
    timestamp: datetime,
    id: str | None = None,
) -> VaultOpRecord:
    return VaultOpRecord(
        id=id or str(uuid.uuid4()),
        operation=operation,
        amount=amount,
        tx_hash=tx_hash,
        explorer_url=explorer_url,
        timestamp=timestamp,
    )


def _recent_vault_records(operations: list[dict]) -> list[VaultOpRecord]:
    return [
        VaultOpRecord(
            id=op["id"],
            operation=op["operation"],
            amount=op["amount"],
            tx_hash=op["tx_hash"],
            explorer_url=op.get("explorer_url"),
            timestamp=datetime.fromisoformat(op["timestamp"]),
        )
        for op in reversed(operations[-20:])
    ]


def _recent_mpt_records(attestations: list[dict]) -> list[MPTAttestationRecord]:
    return [
        MPTAttestationRecord(
            id=attestation["id"],
            issuance_id=attestation["issuance_id"],
            recipient=attestation["recipient"],
            payment_id=attestation["payment_id"],
            amount_settled=attestation["amount_settled"],
            tx_hash=attestation["tx_hash"],
            explorer_url=attestation.get("explorer_url"),
            timestamp=datetime.fromisoformat(attestation["timestamp"]),
        )
        for attestation in reversed(attestations[-20:])
    ]


def _mpt_record(result, *, payment_id: str, amount_settled: float) -> MPTAttestationRecord:
    return MPTAttestationRecord(
        id=str(uuid.uuid4()),
        issuance_id=result.issuance_id,
        recipient=result.recipient,
        payment_id=payment_id,
        amount_settled=amount_settled,
        tx_hash=result.tx_hash,
        explorer_url=result.explorer_url,
        timestamp=result.timestamp,
    )
