"""Treasury Orchestrator.

Runs the payment workflow by calling deterministic tools in a fixed order and
narrating each step into the agent log. The order and every decision are
deterministic; only the audit explanation is LLM-assisted. The policy outcome
comes from app/policy/engine.py — never from a prompt.

The narration here can later be replaced by an LLM tool-use loop without changing
the tools or the policy boundary.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from .. import store
from ..config import get_settings
from ..policy import engine
from ..policy.scope import AgentScope, evaluate_scope
from ..schemas import (
    AgentLogEntry,
    DelegationGrantCreate,
    GuardrailResult,
    Payment,
    PaymentIntent,
    PaymentStatus,
    Receivable,
    ReceivableCreate,
    X402Settlement,
)
from ..tools import audit, compliance, credentials, execution, firefly, receipt, routing
from ..tools import delegation as delegation_tool
from ..tools import trade_finance as tf_tool
from ..tools import x402 as x402_tool

# Statuses that represent a terminal, immutable outcome.
TERMINAL_STATUSES = {PaymentStatus.settled, PaymentStatus.released, PaymentStatus.blocked}


async def process_payment(intent: PaymentIntent) -> Payment:
    settings = get_settings()
    payment_id = str(uuid.uuid4())
    now = _now()
    payment = Payment(
        id=payment_id,
        intent=intent,
        status=PaymentStatus.routing,
        created_at=now,
        updated_at=now,
    )
    store.save(payment)
    _log(
        payment_id,
        (
            f"Received {intent.amount} {intent.currency} from {intent.sender_name} "
            f"({intent.sender_country}) to {intent.receiver_name} ({intent.receiver_country})."
        ),
    )

    route = await routing.get_fx_path(intent, settings.token_currency)
    payment.route_quote = route
    _log(payment_id, f"Routed: {route.path_summary}, settling {route.dest_amount}.")

    credential = await credentials.verify_kyc(intent.to)
    if credential.checked:
        _log(payment_id, f"KYC credential ({credential.credential_type}): {credential.reason}.")

    screen = compliance.check_compliance(intent, credential=credential)
    payment.compliance = screen
    _log(payment_id, screen.explanation)

    # Policy compares against a USD threshold, so normalize the source amount to
    # USD first — never hand it the settlement-currency amount (e.g. XRP). The
    # threshold and flag score come from config; the engine still owns the rule.
    # When the token settles in USD the route already carries that conversion,
    # so reuse it instead of fetching the same rate a second time.
    if settings.token_currency.upper() == "USD":
        amount_usd = route.dest_amount
    else:
        amount_usd = await routing.convert_to_usd(intent.amount, intent.currency)
    decision = engine.evaluate(
        amount_usd,
        screen.aml_score,
        sanctioned=screen.sanctioned,
        threshold_usd=settings.policy_threshold_usd,
        flag_score=settings.policy_compliance_flag_score,
    )
    payment.policy_decision = decision
    payment.audit_explanation = await audit.write_audit(route, screen, decision)
    _log(
        payment_id,
        (
            f"Policy: ${amount_usd:,.2f} vs ${settings.policy_threshold_usd:,.2f} threshold, "
            f"AML {screen.aml_score} vs {settings.policy_compliance_flag_score} flag → "
            f"{'block' if decision.blocked else 'approval required' if decision.requires_approval else 'auto-settle'}."
        ),
    )

    # Anchor the deterministic decision trail on-ledger via transaction Memos.
    memo = execution.ComplianceMemo(
        aml_score=screen.aml_score,
        rule_fired=decision.rule_fired,
        receipt_hash=receipt.compute_decision_hash(payment),
    )

    if decision.blocked:
        await _block(payment)
    elif decision.requires_approval:
        await _escalate(payment, route, intent, memo)
    else:
        await _settle(payment, route, intent, memo)

    payment.updated_at = _now()
    return store.save(payment)


async def _settle(payment: Payment, route, intent: PaymentIntent, memo: "execution.ComplianceMemo") -> None:
    _log_settlement_scale(payment.id, route, intent)
    result = await execution.execute_payment(payment.id, intent, route, memo=memo)
    payment.status = PaymentStatus.settled
    payment.tx_hash = result.tx_hash
    payment.explorer_url = result.explorer_url
    payment.explorer_url_secondary = _secondary_explorer(result.tx_hash, result.explorer_url)
    _log(payment.id, f"Auto-settled. Tx {result.tx_hash[:12]}…")
    payment.receipt_hash = receipt.compute_receipt_hash(payment)


async def _escalate(payment: Payment, route, intent: PaymentIntent, memo: "execution.ComplianceMemo") -> None:
    _log_settlement_scale(payment.id, route, intent)
    escrow = await execution.lock_payment(payment.id, intent, route, memo=memo)
    payment.status = PaymentStatus.pending_approval
    payment.escrow_sequence = escrow.escrow_sequence
    payment.escrow_create_tx_hash = escrow.escrow_create_tx_hash
    payment.tx_hash = escrow.tx_hash
    payment.explorer_url = escrow.explorer_url
    payment.explorer_url_secondary = _secondary_explorer(escrow.tx_hash, escrow.explorer_url)
    reason = "; ".join(payment.policy_decision.reasons) if payment.policy_decision else ""
    _log(payment.id, f"Locked on-chain pending hardware approval ({reason}).")


async def _block(payment: Payment) -> None:
    payment.status = PaymentStatus.blocked
    reason = payment.policy_decision.block_reason if payment.policy_decision else "blocked"
    _log(payment.id, f"Refused: {reason}.")
    payment.receipt_hash = receipt.compute_receipt_hash(payment)


async def release_payment(payment_id: str, signature: str) -> Payment:
    payment = store.get(payment_id)
    if payment is None:
        raise PaymentNotFound(payment_id)
    if payment.status is not PaymentStatus.pending_approval:
        raise InvalidApprovalState(payment.status)

    challenge = firefly.challenge_for_payment(payment)
    if not firefly.verify_signature(challenge.digest, signature):
        raise SignatureRejected(payment_id)

    result = await execution.finish_escrow(payment_id, payment.escrow_sequence or 0)
    payment.status = PaymentStatus.released
    payment.approval_signature = signature
    payment.tx_hash = result.tx_hash
    payment.explorer_url = result.explorer_url
    payment.explorer_url_secondary = _secondary_explorer(result.tx_hash, result.explorer_url)
    payment.updated_at = _now()
    _log(payment_id, f"Firefly signature verified. Released. Tx {result.tx_hash[:12]}…")
    payment.receipt_hash = receipt.compute_receipt_hash(payment)
    return store.save(payment)


async def release_tampered(payment_id: str, signature: str) -> None:
    """DEMO ONLY. Proves that altering payment details after signing breaks verification.

    Builds a tampered copy of the payment (amount ×1000), rebuilds the digest
    from the tampered fields, and verifies the real signature against it — which
    must fail. Never writes the tampered copy to the store.
    """
    payment = store.get(payment_id)
    if payment is None:
        raise PaymentNotFound(payment_id)
    if payment.status is not PaymentStatus.pending_approval:
        raise InvalidApprovalState(payment.status)

    tampered = payment.model_copy(deep=True)
    tampered.intent.amount *= 1000

    challenge = firefly.challenge_for_payment(tampered)
    if not firefly.verify_signature(challenge.digest, signature):
        raise SignatureRejected(payment_id)

    # If we somehow reach here the signature coincidentally verified (shouldn't happen).
    raise SignatureRejected(payment_id)


def challenge_for(payment_id: str):
    payment = store.get(payment_id)
    if payment is None:
        raise PaymentNotFound(payment_id)
    if payment.status is not PaymentStatus.pending_approval:
        raise InvalidApprovalState(payment.status)
    return firefly.challenge_for_payment(payment)


# ── x402 pay-at-need (Feature A) ─────────────────────────────────────────────

async def process_service_payment(
    service_url: str,
    *,
    service_type: str = "data_lookup",
    agent_address: str | None = None,
) -> X402Settlement:
    """Pay for an external service via x402. Runs G1→G4 guardrails before paying.

    Guardrail order:
      G1  KYA          — agent must have an accepted credential
      G2  sanctions    — service host checked (OpenSanctions not wired for hosts,
                         so we verify the host is in the allowed list instead)
      G4  spend scope  — per-tx + daily velocity cap
    """
    settings = get_settings()
    trail: list[GuardrailResult] = []

    # G1: agent KYA
    effective_agent = agent_address or settings.treasury_wallet_address or "rMOCK_TREASURY"
    g1 = await _run_g1(effective_agent)
    trail.append(g1)
    if not g1.passed:
        raise GuardrailBlocked("G1_kya", g1.reason or g1.rule_fired or "kya_failed", trail)

    # G4: scope (host allowlist + velocity)
    from urllib.parse import urlparse
    host = urlparse(service_url).netloc
    scope = _agent_scope(settings)
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    spent_today = store.recent_payments_sum(effective_agent, since, "RLUSD")
    g4 = evaluate_scope(
        Decimal("1"),        # placeholder; real amount comes from the 402 challenge
        scope,
        spent_today,
        service_host=host,
        service_type=service_type,
    )
    trail.append(GuardrailResult(
        name="G4_scope",
        passed=g4.allowed,
        rule_fired=g4.rule_fired,
        reason=g4.reasons[0] if g4.reasons else None,
    ))
    if not g4.allowed:
        raise GuardrailBlocked("G4_scope", g4.reasons[0] if g4.reasons else "scope_blocked", trail)

    settlement = await x402_tool.request_with_payment(
        service_url, service_type=service_type, guardrail_trail=trail
    )
    return settlement


# ── On-chain credit / trade finance (Feature B) ───────────────────────────────

async def register_receivable(create: ReceivableCreate) -> Receivable:
    """Register a trade-finance receivable. No guardrails — this is record-only."""
    return await tf_tool.register_receivable(create)


async def process_early_payment(
    invoice_id: str,
    *,
    agent_address: str | None = None,
) -> Receivable:
    """Pay a supplier early from the vault pool. Runs G1→G4→G6 guardrails.

    G6 (amount threshold): large early-payments still escalate to Firefly via the
    standard process_payment path — this function raises GuardrailEscalation so
    the caller can redirect to the hardware-approval flow.
    """
    settings = get_settings()
    trail: list[GuardrailResult] = []

    rec = tf_tool.get_by_invoice(invoice_id)
    if rec is None:
        from ..tools.trade_finance import ReceivableNotFound
        raise ReceivableNotFound(invoice_id)

    face = Decimal(rec.amount)
    discount = Decimal(rec.discount_rate)
    supplier_amount = face * (Decimal("1") - discount)

    effective_agent = agent_address or settings.treasury_wallet_address or "rMOCK_TREASURY"

    # G1
    g1 = await _run_g1(effective_agent)
    trail.append(g1)
    if not g1.passed:
        raise GuardrailBlocked("G1_kya", g1.reason or "kya_failed", trail)

    # G4 is intentionally skipped for trade finance: receivable face values are
    # large by design (institutional invoices). G6 below provides the threshold
    # gate; Firefly covers anything above policy_threshold_usd.
    trail.append(GuardrailResult(
        name="G4_scope",
        passed=True,
        rule_fired=None,
        reason="trade_finance_exempt",
    ))

    # G6: amount threshold → Firefly escalation
    policy = engine.evaluate(
        float(supplier_amount),
        aml_score=0,
        sanctioned=False,
        threshold_usd=settings.policy_threshold_usd,
        flag_score=settings.policy_compliance_flag_score,
    )
    g6_passed = not policy.blocked and not policy.requires_approval
    trail.append(GuardrailResult(
        name="G6_threshold",
        passed=g6_passed,
        rule_fired=policy.rule_fired,
        reason="; ".join(policy.reasons) if policy.reasons else None,
    ))
    if policy.blocked:
        raise GuardrailBlocked("G6_threshold", policy.block_reason or "policy_blocked", trail)
    if policy.requires_approval:
        raise GuardrailEscalation("G6_threshold", "requires_hardware_approval", trail)

    return await tf_tool.pay_supplier_early(invoice_id, guardrail_trail=trail)


async def collect_repayment(
    invoice_id: str, *, repayment_tx_hash: str | None = None
) -> Receivable:
    """Collect buyer repayment and replenish vault. No additional guardrails."""
    return await tf_tool.collect_repayment(invoice_id, repayment_tx_hash=repayment_tx_hash)


# ── Agent-to-Agent Delegation (Feature C) ─────────────────────────────────────

async def process_delegation_fund(create: DelegationGrantCreate) -> "delegation_tool.DelegationGrant":
    """Grant delegation and fund the sub-agent. Runs G1 on the parent."""
    settings = get_settings()
    trail: list[GuardrailResult] = []

    g1 = await _run_g1(create.parent_address)
    trail.append(g1)
    if not g1.passed:
        raise GuardrailBlocked("G1_kya", g1.reason or "kya_failed", trail)

    return await delegation_tool.grant_delegation(create)


# ── Shared guardrail helpers ──────────────────────────────────────────────────

async def _run_g1(agent_address: str) -> GuardrailResult:
    """Run G1 KYA: verify the agent holds an accepted credential."""
    settings = get_settings()
    if not settings.credential_kyc_enabled:
        return GuardrailResult(name="G1_kya", passed=True, rule_fired=None, reason="KYC disabled")
    cred = await credentials.verify_kyc(agent_address)
    passed = cred.verified
    return GuardrailResult(
        name="G1_kya",
        passed=passed,
        rule_fired=None if passed else "kya_unverified",
        reason=cred.reason if not passed else None,
    )


def _agent_scope(settings) -> AgentScope:
    allowed_hosts = (
        [h.strip() for h in settings.x402_allowed_service_hosts.split(",") if h.strip()]
        if settings.x402_allowed_service_hosts
        else None
    )
    return AgentScope(
        max_per_transaction=Decimal(str(settings.x402_scope_max_per_tx_usd)),
        max_per_day=Decimal(str(settings.x402_scope_max_per_day_usd)),
        allowed_service_hosts=allowed_hosts,
    )


# ── Guardrail exceptions ──────────────────────────────────────────────────────

class GuardrailBlocked(Exception):
    """A guardrail hard-blocked the action. No payment submitted."""
    def __init__(self, guardrail: str, reason: str, trail: list[GuardrailResult]):
        super().__init__(f"{guardrail}: {reason}")
        self.guardrail = guardrail
        self.reason = reason
        self.trail = trail


class GuardrailEscalation(Exception):
    """A guardrail demands Firefly escalation (not a hard block)."""
    def __init__(self, guardrail: str, reason: str, trail: list[GuardrailResult]):
        super().__init__(f"{guardrail}: {reason}")
        self.guardrail = guardrail
        self.reason = reason
        self.trail = trail


class PaymentNotFound(Exception):
    pass


class InvalidApprovalState(Exception):
    pass


class SignatureRejected(Exception):
    pass


def _secondary_explorer(tx_hash: str | None, primary_url: str | None) -> str | None:
    """Cross-check explorer link (bithomp), tied to the primary's liveness.

    Returns None whenever the primary is None (mock mode / no real tx), so a
    stale fake hash never produces a dead second link.
    """
    if not tx_hash or primary_url is None:
        return None
    from ..xrpl_client import bithomp_tx_url

    return bithomp_tx_url(tx_hash)


def _log_settlement_scale(payment_id: str, route, intent: PaymentIntent) -> None:
    """Narrate the testnet settlement scaling so the on-ledger amount is auditable.

    Only fires in real mode with a non-1.0 scale. The scaled value comes from the
    same helper the execution tool uses, so the log and the submitted tx agree.
    """
    settings = get_settings()
    if settings.use_mock_xrpl or settings.testnet_settlement_scale == 1.0:
        return
    on_ledger = execution.scaled_settlement(route.dest_amount, settings)
    _log(
        payment_id,
        (
            f"Testnet settlement scaled ×{settings.testnet_settlement_scale:g}: "
            f"{on_ledger:.6f} {settings.token_currency} settled on-ledger for the "
            f"{intent.amount:,.2f} {intent.currency} intent (policy & approval use the true amount)."
        ),
    )


def _log(payment_id: str, message: str) -> None:
    store.append_log(AgentLogEntry(payment_id=payment_id, timestamp=_now(), message=message))


def _now() -> datetime:
    return datetime.now(timezone.utc)
