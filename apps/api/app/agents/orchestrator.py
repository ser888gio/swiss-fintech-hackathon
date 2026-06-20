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
from ..insurance import binding as insurance_binding
from ..insurance import engine as insurance_engine
from ..policy import engine
from ..policy.guardrail import evaluate_guardrails
from ..policy.scope import AgentScope, evaluate_scope
from ..schemas import (
    AgentLogEntry,
    BindRequest,
    CoverLine,
    ConstraintResult,
    DelegationGrantCreate,
    InsuranceQuoteRequest,
    GuardrailResult,
    Payment,
    PaymentIntent,
    PaymentStatus,
    PolicyDecision,
    Receivable,
    ReceivableCreate,
    ServicePaymentRecord,
    X402Settlement,
)
from ..tools import audit, compliance, credentials, execution, firefly, receipt, routing
from ..tools import delegation as delegation_tool
from ..tools import trade_finance as tf_tool
from ..tools import x402 as x402_tool

# Statuses that represent a terminal, immutable outcome.
TERMINAL_STATUSES = {PaymentStatus.settled, PaymentStatus.released, PaymentStatus.blocked}


async def process_payment(
    intent: PaymentIntent,
    agent_id: str | None = None,
    agent_scope: "AgentScope | None" = None,
) -> Payment:
    settings = get_settings()
    payment_id = str(uuid.uuid4())
    now = _now()
    payment = Payment(
        id=payment_id,
        intent=intent,
        status=PaymentStatus.routing,
        agent_id=agent_id,
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
    # Run guardrails: G2 (sanctions) + G6 (threshold) for all payments;
    # G4 (scope) added when a business agent scope is provided.
    has_agent_scope = agent_scope is not None and agent_id is not None
    spent_today = Decimal("0")
    if has_agent_scope:
        since = _now() - timedelta(hours=24)
        spent_today = store.agent_payments_sum(agent_id, since, intent.currency)

    g_result = evaluate_guardrails(
        context_kind="agent_payment" if has_agent_scope else "payment",
        sanctioned=screen.sanctioned,
        aml_score=screen.aml_score,
        amount=Decimal(str(amount_usd)),
        spent_today=spent_today,
        scope_max_per_tx=agent_scope.max_per_transaction if agent_scope else Decimal("0"),
        scope_max_per_day=agent_scope.max_per_day if agent_scope else Decimal("0"),
        threshold_usd=settings.policy_threshold_usd,
        flag_score=settings.policy_compliance_flag_score,
    )
    payment.guardrail_trail = list(g_result.guardrail_trail)

    if has_agent_scope:
        g4 = next((s for s in g_result.guardrail_trail if s.name == "G4_scope"), None)
        if g4:
            _log(
                payment_id,
                f"Agent scope [{agent_id}]: "
                + (g4.rule_fired or "all checks passed")
                + (f" — {g4.reason}" if g4.reason else ""),
            )

    decision = _policy_decision_from(g_result)

    # Explicit demo switch: Testnet/Devnet can exercise a real direct payment
    # without the local Firefly bridge. Mainnet always fails closed and retains
    # the approval requirement, even if the switch is disabled by mistake.
    if decision.requires_approval and not getattr(settings, "firefly_confirmation_enabled", True):
        if settings.xrpl_network == "xrpl:0":
            _log(
                payment_id,
                "Firefly bypass ignored on Mainnet; hardware approval remains required.",
            )
        else:
            original_rule = decision.rule_fired or "policy_escalation"
            decision = decision.model_copy(update={
                "requires_approval": False,
                "rule_fired": "firefly_bypass_non_production",
                "reasons": list(decision.reasons) + [
                    f"Firefly confirmation disabled for {settings.xrpl_network}; "
                    f"original escalation rule: {original_rule}"
                ],
            })
            _log(
                payment_id,
                f"Non-production Firefly bypass applied on {settings.xrpl_network}.",
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

    if getattr(settings, "legacy_inline_cover_enabled", False) and insurance_engine.cover_requirement(
        intent.cover_required,
        amount_usd,
        intent.cover_required_above_usd
        if intent.cover_required_above_usd is not None
        else settings.insurance_cover_required_above_usd,
    ) == "REQUIRED":
        quote_request = InsuranceQuoteRequest(
            agent_address=intent.from_account,
            score_band="STANDARD",
            txn_context={
                "category": intent.purpose,
                "tenorBand": "short",
                "cptyBand": "standard" if intent.receiver_entity_type.value == "company" else "elevated",
                "firstSeen": False,
                "amount": f"{amount_usd:.6f}",
                "amountZ": min(amount_usd / max(settings.policy_threshold_usd, 1.0), 3.0),
                "velocityZ": 0.0,
                "concentrationZ": 0.0,
                "activeLines": [CoverLine.merchant_default],
            },
        )
        quote = await insurance_binding.quote(quote_request)
        payment.cover = quote
        if quote.decision.value == "DECLINE":
            payment.policy_decision = decision.model_copy(
                update={
                    "blocked": True,
                    "requires_approval": False,
                    "block_reason": quote.reason,
                    "reasons": list(decision.reasons) + [quote.reason],
                    "rule_fired": "insurance_decline",
                }
            )
            await _block(payment)
            payment.updated_at = _now()
            return store.save(payment)
        if quote.decision.value == "REVIEW":
            payment.policy_decision = decision.model_copy(
                update={
                    "requires_approval": True,
                    "reasons": list(decision.reasons) + [quote.reason],
                    "rule_fired": decision.rule_fired or "insurance_review",
                }
            )
        else:
            premium = await insurance_binding.bind(
                BindRequest(
                    job_id=payment_id,
                    agent_address=intent.from_account,
                    score_band=quote_request.score_band,
                    currency=settings.token_currency,
                    quote=quote,
                )
            )
            _log(
                payment_id,
                (
                    f"Insurance auto-bound: premium {premium.premium_amount} {premium.currency} "
                    f"({quote.receipt_hash[:12]}...)."
                ),
            )

    # Reserve agent spend before submitting (prevents double-spend on concurrent runs).
    if agent_id is not None and not decision.blocked:
        store.reserve_agent_spend(agent_id, payment_id, Decimal(str(amount_usd)), intent.currency)

    if decision.blocked:
        await _block(payment)
        if agent_id is not None:
            store.release_agent_spend(agent_id, payment_id)
    elif decision.requires_approval:
        await _escalate(payment, route, intent, memo)
        if agent_id is not None:
            store.commit_agent_spend(agent_id, payment_id)
    else:
        await _settle(payment, route, intent, memo)
        if agent_id is not None:
            store.commit_agent_spend(agent_id, payment_id)

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
    agent_id: str | None = None,
    agent_scope: AgentScope | None = None,
    category: str | None = None,
) -> X402Settlement:
    """Challenge → full-scope policy → reserve → direct pay → verified retry.

    The 402 price is fetched before any policy decision. x402 never enters an
    approval flow: scope or G6 review outcomes are hard blocks with no payment.
    """
    settings = get_settings()
    from urllib.parse import urlparse

    effective_agent = agent_address or settings.treasury_wallet_address or "rMOCK_TREASURY"
    requirement = await x402_tool.fetch_requirement(service_url)
    host = urlparse(requirement.service_url).netloc
    scope = agent_scope or _agent_scope(settings)
    agent_key = agent_id or effective_agent
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    spent_today = store.agent_payments_sum(
        agent_key, since, requirement.asset_currency
    )
    cred = await credentials.verify_kyc(effective_agent)
    trail: list[GuardrailResult] = []
    kya_ok = cred.verified if settings.credential_kyc_enabled else True
    trail.append(GuardrailResult(
        name="G1_kya",
        passed=kya_ok,
        rule_fired=None if kya_ok else "kya_unverified",
        reason=None if kya_ok else "agent credential not verified",
    ))
    if not kya_ok:
        _save_service_outcome(requirement, host, agent_id, "blocked", trail)
        raise GuardrailBlocked("kya_unverified", "agent credential not verified", trail)

    scope_result = evaluate_scope(
        Decimal(requirement.amount),
        scope,
        spent_today,
        payee_address=requirement.pay_to,
        service_host=host,
        service_type=service_type,
        asset=requirement.asset_currency,
        network=requirement.network,
        category=category,
        payee_is_known_merchant=_is_known_merchant(requirement, scope),
    )
    trail.append(GuardrailResult(
        name="G4_scope",
        passed=scope_result.allowed,
        rule_fired=scope_result.rule_fired,
        reason=scope_result.reasons[0] if scope_result.reasons else None,
    ))
    if not scope_result.allowed:
        reason = scope_result.reasons[0] if scope_result.reasons else "blocked"
        if scope_result.requires_approval:
            reason = f"over approval threshold: {reason}"
        _save_service_outcome(requirement, host, agent_id, "blocked", trail)
        raise GuardrailBlocked(scope_result.rule_fired or "G4_scope", reason, trail)

    threshold = engine.evaluate(
        float(Decimal(requirement.amount)),
        0,
        threshold_usd=settings.policy_threshold_usd,
        flag_score=settings.policy_compliance_flag_score,
    )
    g6_ok = not threshold.blocked and not threshold.requires_approval
    trail.append(GuardrailResult(
        name="G6_threshold",
        passed=g6_ok,
        rule_fired=threshold.rule_fired,
        reason="; ".join(threshold.reasons) if threshold.reasons else None,
    ))
    if not g6_ok:
        reason = "; ".join(threshold.reasons) or "over approval threshold"
        _save_service_outcome(requirement, host, agent_id, "blocked", trail)
        raise GuardrailBlocked(threshold.rule_fired or "G6_threshold", reason, trail)

    reserved = store.reserve_agent_spend(
        agent_key,
        requirement.invoice_id,
        Decimal(requirement.amount),
        requirement.asset_currency,
    )
    if not reserved:
        raise x402_tool.X402Rejected("invoice was already reserved or settled")

    try:
        settlement = await x402_tool.settle_x402(
            requirement,
            guardrail_trail=trail,
            agent_id=agent_id,
        )
        await x402_tool.retry_with_proof(requirement, settlement)
        store.commit_agent_spend(agent_key, requirement.invoice_id)
    except Exception as exc:
        store.release_agent_spend(agent_key, requirement.invoice_id)
        failure_trail = trail + [GuardrailResult(
            name="merchant_proof",
            passed=False,
            rule_fired="settlement_or_proof_failed",
            reason=str(exc),
        )]
        _save_service_outcome(requirement, host, agent_id, "blocked", failure_trail)
        raise

    record = _save_service_outcome(
        requirement,
        host,
        agent_id,
        "settled",
        trail,
        settlement=settlement,
    )
    if getattr(settings, "insurance_enabled", False):
        try:
            quote = await insurance_binding.quote(InsuranceQuoteRequest(
                agent_address=effective_agent,
                score_band="STANDARD",
                txn_context={
                    "category": category or service_type,
                    "tenorBand": "instant",
                    "cptyBand": "standard",
                    "firstSeen": False,
                    "amount": requirement.amount,
                    "amountZ": 0.0,
                    "velocityZ": 0.0,
                    "concentrationZ": 0.0,
                    "activeLines": [CoverLine.merchant_default],
                },
            ))
            record.cover = await insurance_binding.bind_service_cover(
                requirement.invoice_id, quote
            )
            record.updated_at = _now()
            store.update_service_payment(record)
        except Exception:
            # Cover is an integration hook; settlement remains authoritative.
            pass
    return settlement


def _is_known_merchant(requirement, scope: AgentScope) -> bool:
    return "/merchants/" in requirement.service_url or (
        scope.allowed_addresses is not None
        and requirement.pay_to in scope.allowed_addresses
    )


def _save_service_outcome(
    requirement,
    host: str,
    agent_id: str | None,
    status: str,
    trail: list[GuardrailResult],
    *,
    settlement: X402Settlement | None = None,
) -> ServicePaymentRecord:
    now = _now()
    audit_event_id = settlement.audit_event_id if settlement else None
    if settlement is None:
        from ..tools import audit_log
        event = audit_log.append(
            event_type="x402_blocked",
            actor="policy_engine",
            context_kind="service_payment",
            payload={
                "agent_id": agent_id,
                "invoice_id": requirement.invoice_id,
                "service_url": requirement.service_url,
                "amount": requirement.amount,
                "currency": requirement.asset_currency,
                "guardrail_trail": [g.model_dump(mode="json") for g in trail],
            },
        )
        audit_event_id = event.event_id
    return store.save_service_payment(ServicePaymentRecord(
        id=str(uuid.uuid4()),
        agent_id=agent_id,
        status=status,
        service_host=host,
        invoice_id=requirement.invoice_id,
        asset_currency=requirement.asset_currency,
        asset_issuer=requirement.asset_issuer,
        amount=requirement.amount,
        tx_hash=settlement.tx_hash if settlement else None,
        explorer_url=settlement.explorer_url if settlement else None,
        guardrail_trail=trail,
        audit_event_id=audit_event_id,
        created_at=now,
        updated_at=now,
    ))


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
    rec = tf_tool.get_by_invoice(invoice_id)
    if rec is None:
        from ..tools.trade_finance import ReceivableNotFound
        raise ReceivableNotFound(invoice_id)

    face = Decimal(rec.amount)
    discount = Decimal(rec.discount_rate)
    supplier_amount = face * (Decimal("1") - discount)

    effective_agent = agent_address or settings.treasury_wallet_address or "rMOCK_TREASURY"
    cred = await credentials.verify_kyc(effective_agent)

    # G4 is intentionally skipped for trade finance: receivable face values are
    # large by design (institutional invoices). G6 provides the threshold gate;
    # Firefly covers anything above policy_threshold_usd.
    result = evaluate_guardrails(
        context_kind="loan_underwrite",  # G1 + G6 (no G4 for trade finance)
        agent_credential_verified=cred.verified if settings.credential_kyc_enabled else True,
        sanctioned=False,
        aml_score=0,
        amount=supplier_amount,
        threshold_usd=settings.policy_threshold_usd,
        flag_score=settings.policy_compliance_flag_score,
    )
    trail = result.guardrail_trail
    if not result.allowed:
        if result.action == "review":
            raise GuardrailEscalation(result.rule_fired or "G6_threshold", "requires_hardware_approval", trail)
        raise GuardrailBlocked(result.rule_fired or "guardrail", result.reasons[0] if result.reasons else "blocked", trail)

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
    cred = await credentials.verify_kyc(create.parent_address)

    result = evaluate_guardrails(
        context_kind="delegation_fund",
        agent_credential_verified=cred.verified if settings.credential_kyc_enabled else True,
        amount=Decimal(str(create.max_total)),
        spent_today=Decimal("0"),
        scope_max_per_tx=Decimal(str(create.max_per_tx)),
        scope_max_per_day=Decimal(str(create.max_per_day)),
    )
    if not result.allowed:
        raise GuardrailBlocked(result.rule_fired or "guardrail", result.reasons[0] if result.reasons else "blocked", result.guardrail_trail)

    return await delegation_tool.grant_delegation(create)


# ── Shared helpers ────────────────────────────────────────────────────────────

def _policy_decision_from(result: ConstraintResult) -> PolicyDecision:
    """Derive a PolicyDecision from a ConstraintResult for downstream consumers."""
    blocked = result.action == "block"
    return PolicyDecision(
        requires_approval=result.action == "review",
        blocked=blocked,
        rule_fired=result.rule_fired,
        reasons=result.reasons,
        block_reason=result.reasons[0] if blocked and result.reasons else None,
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
