"""Execution tool.

Submits XRPL transactions: a direct token Payment for auto-settled payments, an
EscrowCreate to lock large/flagged payments, and an EscrowFinish to release them
once a Firefly signature has been verified.

In mock mode (settings.use_mock_xrpl) this returns deterministic fake tx hashes so
the full workflow runs offline. The real submission paths are wired in at the
hackathon once testnet wallets and the token trust line are set up.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ..config import get_settings
from ..schemas import ExecutionResult, PaymentIntent, PaymentStatus, RouteQuote


@dataclass
class EscrowResult:
    escrow_sequence: int
    tx_hash: str
    explorer_url: str | None


async def execute_payment(payment_id: str, intent: PaymentIntent, route: RouteQuote) -> ExecutionResult:
    """Direct token Payment for an auto-settled payment."""
    if get_settings().use_mock_xrpl:
        tx_hash = _mock_hash("pay", payment_id)
        return ExecutionResult(
            tx_hash=tx_hash,
            explorer_url=None,
            status=PaymentStatus.settled,
        )
    raise NotImplementedError("Real XRPL Payment submission — wire up at hackathon")


async def lock_payment(payment_id: str, intent: PaymentIntent, route: RouteQuote) -> EscrowResult:
    """EscrowCreate to lock funds for a payment that needs hardware approval."""
    if get_settings().use_mock_xrpl:
        tx_hash = _mock_hash("escrow", payment_id)
        return EscrowResult(
            escrow_sequence=_mock_sequence(payment_id),
            tx_hash=tx_hash,
            explorer_url=None,
        )
    raise NotImplementedError("Real XRPL EscrowCreate — wire up at hackathon")


async def finish_escrow(payment_id: str, escrow_sequence: int) -> ExecutionResult:
    """EscrowFinish to release a locked payment. Callers MUST verify the Firefly
    signature before invoking this — verification is not done here."""
    if get_settings().use_mock_xrpl:
        tx_hash = _mock_hash("finish", payment_id)
        return ExecutionResult(
            tx_hash=tx_hash,
            explorer_url=None,
            status=PaymentStatus.released,
        )
    raise NotImplementedError("Real XRPL EscrowFinish — wire up at hackathon")


def _mock_hash(kind: str, payment_id: str) -> str:
    return hashlib.sha256(f"{kind}:{payment_id}".encode()).hexdigest().upper()


def _mock_sequence(payment_id: str) -> int:
    return int(hashlib.sha256(payment_id.encode()).hexdigest()[:6], 16)
