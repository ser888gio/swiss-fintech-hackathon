"""Cover tool — async settlement layer for annual agent insurance.

quote()  → pricing.price_cover() (pure, no I/O)
bind()   → re-quote, reserve capacity, settle premium on-ledger, create policy
claim()  → load immutable payment + policy, reconcile(), claim_policy.evaluate(),
           settle payout on-ledger, decrement cover_remaining, reprice posterior

Determinism boundary: the LLM never calls this. All financial decisions are
deterministic (reconcile + claim_policy); narrate_claim() is cosmetic only.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from .. import store as payment_store
from .. import xrpl_client
from ..config import get_settings
from ..insurance.engine import PoolState
from ..schemas import (
    CoverBindRequest,
    CoverClaimEvidence,
    CoverLineKind,
    CoverLossBearerKind,
    CoverPolicy,
    CoverPolicyStatus,
    CoverPayout,
    CoverPoolStatus,
    CoverQuote,
    CoverQuoteRequest,
    GuardrailResult,
    PaymentStatus,
)
from . import claim_policy, narrate, pricing, store

log = logging.getLogger(__name__)
_Q2 = Decimal("0.01")


# ── Quote ─────────────────────────────────────────────────────────────────────

def quote(req: CoverQuoteRequest) -> CoverQuote:
    """Price a cover policy (pure, no I/O). Capacity checked against current store."""
    settings = get_settings()
    r = store.get_or_seed_risk(req.agent_address, req.score_band)
    free = store.free_capacity(settings.insurance_pool_first_loss_usd)
    return pricing.price_cover(
        agent_address=req.agent_address,
        score_band=req.score_band,
        cover_cap=req.cover_cap,
        per_claim_limit=req.per_claim_limit,
        term_days=req.term_days,
        lines=req.lines,
        r=r,
        free_capacity=free,
        hallucination_rate=settings.cover_hallucination_rate,
        rate_min=settings.cover_rate_min,
        rate_max=settings.cover_rate_max,
        premium_cap=settings.insurance_premium_cap_usd,
    )


# ── Bind ──────────────────────────────────────────────────────────────────────

async def bind(req: CoverBindRequest, *, simulate_settlement: bool = False) -> CoverPolicy:
    """Re-quote, reserve capacity, settle premium, create policy."""
    settings = get_settings()
    if not settings.cover_enabled:
        raise CoverDisabled("cover_enabled is False")

    q = quote(CoverQuoteRequest(
        agent_address=req.agent_address,
        score_band=req.score_band,
        cover_cap=req.cover_cap,
        per_claim_limit=req.per_claim_limit,
        term_days=req.term_days,
        lines=req.lines,
    ))
    if q.decision != "OFFER":
        raise CoverUnavailable(q.decision, q.reason or "cover not offered")

    premium = Decimal(q.premium).quantize(_Q2, rounding=ROUND_HALF_UP)
    cover_cap_d = Decimal(q.cover_cap).quantize(_Q2)
    per_claim_d = Decimal(q.per_claim_limit).quantize(_Q2)

    # Settle premium from treasury wallet → pool account
    if simulate_settlement:
        tx_hash, explorer_url = xrpl_client.mock_tx_hash("cover_demo_premium", req.agent_address), None
    else:
        tx_hash, explorer_url = await _settle_premium(req.agent_address, premium, settings)

    now = datetime.now(timezone.utc)
    policy_id = str(uuid.uuid4())
    period_end = now + timedelta(days=req.term_days)

    policy = CoverPolicy(
        id=policy_id,
        agent_address=req.agent_address,
        period_start=now,
        period_end=period_end,
        lines=req.lines,
        cover_cap=str(cover_cap_d),
        per_claim_limit=str(per_claim_d),
        premium=str(premium),
        cover_used="0.00",
        cover_remaining=str(cover_cap_d),
        score_band=req.score_band,
        status=CoverPolicyStatus.active,
        premium_tx_hash=tx_hash,
        explorer_url=explorer_url,
        created_at=now,
        updated_at=now,
    )
    store.save_policy(policy)
    store.reserve(policy_id, cover_cap_d)
    store.add_premium(premium)
    _emit_audit("cover_policy_bound", {
        "policy_id": policy_id,
        "agent_address": req.agent_address,
        "premium": str(premium),
        "cover_cap": str(cover_cap_d),
        "term_days": req.term_days,
        "tx_hash": tx_hash,
    })
    return policy


# ── Claim ─────────────────────────────────────────────────────────────────────

async def settle_claim(evidence: CoverClaimEvidence, *, simulate_settlement: bool = False) -> CoverPayout:
    """Load immutable records, reconcile, validate, settle payout."""
    settings = get_settings()
    if not settings.cover_enabled:
        raise CoverDisabled("cover_enabled is False")

    # Load immutable records — never trust client-provided financial data
    policy = store.get_policy(evidence.policy_id)
    if policy is None:
        raise PolicyNotFound(evidence.policy_id)

    payment = payment_store.get(evidence.payment_id)
    if payment is None:
        raise PaymentNotFound(evidence.payment_id)

    # Replay guard
    if store.is_claimed(evidence.payment_id):
        raise AlreadyClaimed(evidence.payment_id)

    # Derive the cover event from the settled payment + its intent ground truth
    from .reconcile import reconcile
    event = reconcile(
        expected_amount=payment.intent.expected_amount,
        executed_amount=payment.intent.amount,
        expected_recipient=payment.intent.expected_recipient,
        executed_recipient=payment.intent.to,
    )
    if event is None:
        raise NoCoveredDivergence(evidence.payment_id)

    # All financial quantities are now derived from the immutable payment record
    loss = event.loss
    line = event.line
    loss_bearer = event.loss_bearer
    merchant = payment.intent.to

    # Dedicated claim policy evaluation
    collusion = store.payout_count_for_pair(policy.agent_address, merchant)
    decision = claim_policy.evaluate(
        policy=policy,
        payment=payment,
        line=line,
        loss=loss,
        merchant=merchant,
        collusion_count=collusion,
    )

    trail: list[GuardrailResult] = [
        GuardrailResult(
            name="CP1_policy_active",
            passed=decision.allowed or decision.block_reason != "policy is not active",
            rule_fired=decision.block_reason if not decision.allowed else None,
            reason=decision.block_reason,
        ),
        GuardrailResult(
            name="CP2_payment_settled",
            passed=payment.status == PaymentStatus.settled,
            rule_fired=None if payment.status == PaymentStatus.settled else "payment_not_settled",
            reason=None if payment.status == PaymentStatus.settled else f"payment is {payment.status.value}",
        ),
        GuardrailResult(
            name="CP7_collusion",
            passed=collusion < 2,
            rule_fired="collusion" if collusion >= 2 else None,
            reason=f"{collusion} prior claims against this merchant" if collusion >= 2 else None,
        ),
    ]

    if not decision.allowed:
        raise ClaimRefused(decision.block_reason or "claim refused")

    # Cap loss to per_claim_limit and cover_remaining
    pcl = Decimal(policy.per_claim_limit)
    remaining = Decimal(policy.cover_remaining)
    payout_amount = min(loss, pcl, remaining).quantize(_Q2, rounding=ROUND_HALF_UP)

    # Determine destination from loss_bearer
    destination = (
        merchant
        if loss_bearer == CoverLossBearerKind.merchant
        else (settings.treasury_wallet_address or "rTREASURY_SELF")
    )

    # Settle on-ledger
    if simulate_settlement:
        tx_hash, explorer_url = xrpl_client.mock_tx_hash("cover_demo_payout", evidence.payment_id), None
    else:
        tx_hash, explorer_url = await _settle_payout(destination, payout_amount, evidence.payment_id, settings)

    # Update policy in-place (decrement cover_remaining)
    now = datetime.now(timezone.utc)
    new_used = (Decimal(policy.cover_used) + payout_amount).quantize(_Q2)
    new_remaining = max(Decimal("0"), remaining - payout_amount).quantize(_Q2)
    new_status = CoverPolicyStatus.exhausted if new_remaining <= Decimal("0") else policy.status
    updated_policy = policy.model_copy(update={
        "cover_used": str(new_used),
        "cover_remaining": str(new_remaining),
        "status": new_status,
        "updated_at": now,
    })
    store.save_policy(updated_policy)
    if new_status == CoverPolicyStatus.exhausted:
        store.release_reservation(policy.id)

    # Replay guard — mark as claimed atomically after all state changes
    store.mark_claimed(evidence.payment_id)
    store.add_claim(payout_amount)

    # Reprice the agent posterior
    store.record_default(policy.agent_address, payout_amount, settings.insurance_tau_days)

    # LLM narration (cosmetic only — payout already decided above)
    narration = narrate.narrate_claim(event, policy)

    receipt = _payout_receipt(evidence.policy_id, evidence.payment_id, str(payout_amount), destination)

    payout = CoverPayout(
        id=str(uuid.uuid4()),
        policy_id=evidence.policy_id,
        payment_id=evidence.payment_id,
        line=line,
        loss_bearer=loss_bearer,
        destination=destination,
        amount_paid=str(payout_amount),
        pool_drawn=str(payout_amount),
        classification=event.classification,
        narration=narration,
        guardrail_trail=trail,
        tx_hash=tx_hash,
        explorer_url=explorer_url,
        receipt_hash=receipt,
        created_at=now,
    )
    store.save_payout(payout)
    _emit_audit("cover_claim_settled", {
        "policy_id": evidence.policy_id,
        "payment_id": evidence.payment_id,
        "line": line.value,
        "classification": event.classification,
        "amount_paid": str(payout_amount),
        "destination": destination,
        "tx_hash": tx_hash,
    })
    return payout


# ── Pool status ───────────────────────────────────────────────────────────────

def get_pool_status() -> CoverPoolStatus:
    settings = get_settings()
    stats = store.pool_stats(settings.insurance_pool_first_loss_usd)
    return CoverPoolStatus(
        first_loss=str(stats["first_loss"].quantize(_Q2)),
        reserved=str(stats["reserved"].quantize(_Q2)),
        free_capacity=str(stats["free_capacity"].quantize(_Q2)),
        currency=settings.token_currency,
        premiums_collected=str(stats["premiums"].quantize(_Q2)),
        claims_paid=str(stats["claims"].quantize(_Q2)),
        capacity_ratio=round(stats["capacity_ratio"], 4),
        policies_active=stats["policies_active"],
        cover_in_force=str(stats["cover_in_force"].quantize(_Q2)),
    )


# ── On-ledger settlement ──────────────────────────────────────────────────────

async def _settle_premium(
    agent_address: str, premium: Decimal, settings
) -> tuple[str, str | None]:
    if settings.use_mock_xrpl:
        return xrpl_client.mock_tx_hash("cover_premium", agent_address), None
    pool_account = settings.cover_pool_account or settings.insurance_vault_address
    if not pool_account:
        raise CoverConfigError("cover_pool_account must be set for real-mode cover settlement")
    return await _pay(pool_account, premium, agent_address, "cover_premium", settings)


async def _settle_payout(
    destination: str, amount: Decimal, payment_id: str, settings
) -> tuple[str | None, str | None]:
    if amount <= Decimal("0"):
        return None, None
    if settings.use_mock_xrpl:
        return xrpl_client.mock_tx_hash("cover_payout", payment_id), None
    if not destination:
        raise CoverConfigError("payout destination is empty")
    return await _pay(destination, amount, payment_id, "cover_payout", settings)


async def _pay(
    destination: str, amount: Decimal, ref: str, kind: str, settings
) -> tuple[str, str | None]:
    from ..ledger import Ledger
    from xrpl.models.transactions import Memo, Payment

    ledger = Ledger(settings)
    wallet = ledger.treasury_wallet
    memo_data = json.dumps({kind: ref}, separators=(",", ":"))
    from ..tools import execution
    on_ledger = execution.scaled_settlement(float(amount), settings)
    tx = Payment(
        account=wallet.address,
        destination=destination,
        amount=xrpl_client.token_amount(settings.token_currency, on_ledger, settings),
        memos=[Memo(
            memo_type="cover/v1".encode().hex().upper(),
            memo_data=memo_data.encode().hex().upper(),
        )],
    )
    result = await ledger.submit(tx, wallet)
    tx_hash = result["hash"]
    return tx_hash, xrpl_client.explorer_tx_url_for(tx_hash, settings.xrpl_endpoint)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _payout_receipt(policy_id: str, payment_id: str, amount: str, destination: str) -> str:
    payload = {"policy_id": policy_id, "payment_id": payment_id, "amount": amount, "destination": destination}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _emit_audit(event_type: str, payload: dict) -> None:
    from ..tools import audit_log
    audit_log.append(
        event_type=event_type,
        actor="cover_tool",
        context_kind="cover",
        payload=payload,
    )


# ── Errors ────────────────────────────────────────────────────────────────────

class CoverError(Exception):
    pass

class CoverDisabled(CoverError):
    pass

class CoverConfigError(CoverError):
    pass

class CoverUnavailable(CoverError):
    def __init__(self, decision: str, reason: str):
        super().__init__(f"{decision}: {reason}")
        self.decision = decision
        self.reason = reason

class PolicyNotFound(CoverError):
    pass

class PaymentNotFound(CoverError):
    pass

class AlreadyClaimed(CoverError):
    pass

class NoCoveredDivergence(CoverError):
    pass

class ClaimRefused(CoverError):
    pass
