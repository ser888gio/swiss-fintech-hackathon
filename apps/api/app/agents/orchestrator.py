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
from datetime import datetime, timezone

from .. import store
from ..config import get_settings
from ..policy import engine
from ..schemas import AgentLogEntry, Payment, PaymentIntent, PaymentStatus
from ..tools import audit, compliance, credentials, execution, firefly, receipt, routing

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
