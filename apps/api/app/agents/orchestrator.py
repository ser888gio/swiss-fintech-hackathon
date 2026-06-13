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
from ..tools import audit, compliance, execution, firefly, receipt, routing

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

    screen = compliance.check_compliance(intent)
    payment.compliance = screen
    _log(payment_id, screen.explanation)

    decision = engine.evaluate(route.dest_amount, screen.aml_score, sanctioned=screen.sanctioned)
    payment.policy_decision = decision
    payment.audit_explanation = await audit.write_audit(route, screen, decision)

    if decision.blocked:
        await _block(payment)
    elif decision.requires_approval:
        await _escalate(payment, route, intent)
    else:
        await _settle(payment, route, intent)

    payment.updated_at = _now()
    return store.save(payment)


async def _settle(payment: Payment, route, intent: PaymentIntent) -> None:
    result = await execution.execute_payment(payment.id, intent, route)
    payment.status = PaymentStatus.settled
    payment.tx_hash = result.tx_hash
    payment.explorer_url = result.explorer_url
    _log(payment.id, f"Auto-settled. Tx {result.tx_hash[:12]}…")
    payment.receipt_hash = receipt.compute_receipt_hash(payment)


async def _escalate(payment: Payment, route, intent: PaymentIntent) -> None:
    escrow = await execution.lock_payment(payment.id, intent, route)
    payment.status = PaymentStatus.pending_approval
    payment.escrow_sequence = escrow.escrow_sequence
    payment.tx_hash = escrow.tx_hash
    payment.explorer_url = escrow.explorer_url
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


def _log(payment_id: str, message: str) -> None:
    store.append_log(AgentLogEntry(payment_id=payment_id, timestamp=_now(), message=message))


def _now() -> datetime:
    return datetime.now(timezone.utc)
