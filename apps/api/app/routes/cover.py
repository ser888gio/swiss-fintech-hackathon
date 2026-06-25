"""Cover routes — annual agent insurance (hallucination line)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from ..config import get_settings
from ..cover import tool as cover_tool
from ..schemas import (
    CoverBindRequest,
    CoverClaimEvidence,
    CoverDemoUnderpaymentRequest,
    CoverPolicy,
    CoverPayout,
    CoverPoolStatus,
    CoverQuote,
    CoverQuoteRequest,
    PaymentIntent,
    PaymentStatus,
    ReceiverEntityType,
)
from .. import store as payment_store

router = APIRouter(prefix="/cover", tags=["cover"])


def _require_cover() -> None:
    if not get_settings().cover_enabled:
        raise HTTPException(status_code=403, detail="cover_enabled is False")


@router.post("/quote", response_model=CoverQuote)
async def cover_quote(req: CoverQuoteRequest) -> CoverQuote:
    _require_cover()
    try:
        return cover_tool.quote(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/bind", response_model=CoverPolicy, status_code=201)
async def cover_bind(req: CoverBindRequest) -> CoverPolicy:
    _require_cover()
    try:
        return await cover_tool.bind(req)
    except cover_tool.CoverUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except cover_tool.CoverError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/policies", response_model=list[CoverPolicy])
async def list_cover_policies(agent: str | None = None) -> list[CoverPolicy]:
    from ..cover import store

    return store.list_policies(agent_address=agent)


@router.get("/policies/{agent_address}", response_model=list[CoverPolicy])
async def agent_cover_policies(agent_address: str) -> list[CoverPolicy]:
    from ..cover import store

    return store.list_policies(agent_address=agent_address)


@router.post("/claim", response_model=CoverPayout, status_code=201)
async def cover_claim(evidence: CoverClaimEvidence) -> CoverPayout:
    """Submit a claim. Evidence = policy_id + payment_id only.
    All financial data is derived server-side from immutable records."""
    _require_cover()
    try:
        return await cover_tool.settle_claim(evidence)
    except cover_tool.AlreadyClaimed as exc:
        raise HTTPException(status_code=409, detail=f"payment already claimed: {exc}")
    except cover_tool.NoCoveredDivergence as exc:
        raise HTTPException(
            status_code=422, detail=f"no covered divergence detected: {exc}"
        )
    except cover_tool.PolicyNotFound as exc:
        raise HTTPException(status_code=404, detail=f"policy not found: {exc}")
    except cover_tool.PaymentNotFound as exc:
        raise HTTPException(status_code=404, detail=f"payment not found: {exc}")
    except cover_tool.ClaimRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except cover_tool.CoverError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/payouts", response_model=list[CoverPayout])
async def list_cover_payouts(policy_id: str | None = None) -> list[CoverPayout]:
    from ..cover import store

    return store.list_payouts(policy_id=policy_id)


@router.get("/pool", response_model=CoverPoolStatus)
async def cover_pool() -> CoverPoolStatus:
    return cover_tool.get_pool_status()


@router.get("/agents/{address}/risk")
async def cover_agent_risk(address: str):
    from ..cover import store

    snap = store.get_agent_risk_snapshot(address)
    if snap is None:
        raise HTTPException(status_code=404, detail="no risk record for this agent")
    return snap


# ── Demo 4.1 — deterministic underpayment claim ───────────────────────────────


@router.post("/demo/underpayment", status_code=201)
async def demo_underpayment(req: CoverDemoUnderpaymentRequest) -> dict:
    """Seed and run the demo 4.1 scenario end-to-end.

    1. Buys a cover policy (if none exists for the demo agent).
    2. Submits a payment where amount ($480) < expected_amount ($500) — below the
       $500 Firefly threshold so it auto-settles without hardware approval.
    3. Files a claim. The reconciler detects the $20 underpayment.
    4. Pool tops up the merchant by $20.

    Returns the settled payment + claim payout + narration.
    """
    _require_cover()
    settings = get_settings()
    if req.paid_amount >= req.invoice_amount:
        raise HTTPException(
            status_code=422, detail="paidAmount must be less than invoiceAmount"
        )

    from decimal import Decimal as _D
    from ..cover import store as cover_store
    from ..cover.store import list_policies

    shortfall = float(req.invoice_amount - req.paid_amount)

    # Resolve agent address — real agent (from agent builder) or the demo treasury wallet.
    agent_address: str
    agent_label: str
    if req.agent_id and req.agent_id != "example-treasury-agent":
        from .agents import _agents as _registered_agents

        agent_obj = _registered_agents.get(req.agent_id)
        if agent_obj is None:
            raise HTTPException(
                status_code=404, detail=f"Unknown agent: {req.agent_id}"
            )
        agent_address = (
            req.agent_id
        )  # agents use their id as their identifier in cover store
        agent_label = agent_obj.name
    else:
        agent_address = settings.treasury_wallet_address or "rDEMO_AGENT"
        agent_label = "Example treasury agent"

    demo_merchant = "rDEMO_MERCHANT_00000000000000000"

    # Reset demo-pair payouts so the collusion guard doesn't block repeated runs.
    cover_store.reset_pair_payouts(agent_address, demo_merchant)

    # Detect whether the agent has an active cover policy.
    active_policies = [
        p
        for p in list_policies(agent_address=agent_address)
        if p.status.value == "active"
    ]

    is_insured = bool(active_policies)
    insured_policy = active_policies[0] if active_policies else None

    if insured_policy:
        # Derive coverage rate from policy: per_claim_limit / shortfall, capped at 1.0.
        pcl = float(_D(insured_policy.per_claim_limit))
        coverage_rate = min(1.0, pcl / shortfall) if shortfall > 0 else 1.0
        per_claim_limit = insured_policy.per_claim_limit
        # Cancel and re-create so cover_remaining is reset between demo runs.
        cover_store.cancel_policy(insured_policy.id)
        q = cover_tool.quote(
            CoverQuoteRequest(
                agent_address=agent_address,
                score_band="STANDARD",
                cover_cap="5000",
                per_claim_limit=per_claim_limit,
                term_days=365,
            )
        )
        if q.decision != "OFFER":
            raise HTTPException(
                status_code=422, detail=f"cover not available: {q.reason}"
            )
        policy = await cover_tool.bind(
            CoverBindRequest(
                agent_address=agent_address,
                score_band="STANDARD",
                cover_cap="5000",
                per_claim_limit=per_claim_limit,
                term_days=365,
                quote=q,
            )
        )
    else:
        # Uninsured agent: no policy exists — synthetic zero-coverage path.
        coverage_rate = 0.0
        per_claim_limit = str(round(shortfall, 2))

        q = cover_tool.quote(
            CoverQuoteRequest(
                agent_address=agent_address,
                score_band="STANDARD",
                cover_cap="5000",
                per_claim_limit=per_claim_limit,
                term_days=365,
            )
        )
        if q.decision != "OFFER":
            raise HTTPException(
                status_code=422, detail=f"cover not available: {q.reason}"
            )
        policy = await cover_tool.bind(
            CoverBindRequest(
                agent_address=agent_address,
                score_band="STANDARD",
                cover_cap="5000",
                per_claim_limit=per_claim_limit,
                term_days=365,
                quote=q,
            )
        )

    # Step 2: create a settled payment with an underpayment hallucination.
    # amount=$480 < expected_amount=$500, same recipient → reconcile detects underpayment.
    # This is below the $500 Firefly threshold so policy engine auto-settles.
    payment_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    intent = PaymentIntent(
        **{
            "from": agent_address,
            "to": demo_merchant,
            "senderName": "Demo Treasury Agent",
            "senderCountry": "CH",
            "receiverName": "Demo Merchant",
            "receiverCountry": "DE",
            "receiverEntityType": ReceiverEntityType.company,
            "purpose": "supplier_invoice",
            "amount": float(req.paid_amount),
            "currency": "RLUSD",
            "reference": f"INV-DEMO-{payment_id[:8]}",
            "expectedAmount": float(req.invoice_amount),
            "expectedRecipient": demo_merchant,
        }
    )

    from ..schemas import Payment

    payment = Payment(
        id=payment_id,
        intent=intent,
        status=PaymentStatus.settled,
        tx_hash=f"DEMO{payment_id.replace('-', '')[:60]}",
        audit_explanation=(
            f"Demo: agent paid ${req.paid_amount} against a ${req.invoice_amount} invoice."
        ),
        created_at=now,
        updated_at=now,
    )
    payment_store.save(payment)

    # Step 3: file the claim — all financial data derived server-side
    payout = await cover_tool.settle_claim(
        CoverClaimEvidence(
            policy_id=policy.id,
            payment_id=payment_id,
        )
    )

    coverage_pct = round(coverage_rate * 100, 1)
    if is_insured:
        coverage_note = (
            f"Agent '{agent_label}' has an active cover policy (per-claim limit ${per_claim_limit}). "
            f"Policy covers {coverage_pct}% of the ${shortfall:.2f} shortfall."
        )
    else:
        coverage_note = (
            f"Agent '{agent_label}' has no active cover policy — uninsured. "
            f"Full shortfall ${shortfall:.2f} is absorbed without insurance backing. "
            "In production, the merchant would bear this loss."
        )

    return {
        "scenario": "demo_4_1_underpayment",
        "settlement_mode": "simulation",
        "is_insured": is_insured,
        "coverage_rate": coverage_rate,
        "description": (
            f"{agent_label} paid ${req.paid_amount} against a ${req.invoice_amount} invoice "
            f"(shortfall ${shortfall:.2f}). "
            f"{coverage_note} "
            "The deterministic reconciler detected the underpayment. "
            f"Cover pool topped up the merchant by ${payout.amount_paid}."
        ),
        "payment": payment.model_dump(mode="json"),
        "policy_id": policy.id,
        "payout": payout.model_dump(mode="json"),
        "narration": payout.narration,
    }
