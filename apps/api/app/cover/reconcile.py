"""Parametric claim trigger — deterministic reconciliation of expected vs executed.

Pure functions, no I/O.  The result of reconcile() drives the payout decision;
the LLM only narrates the 'why' afterward.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..schemas import CoverLineKind, CoverLossBearerKind

_AMOUNT_TOLERANCE = Decimal("0.005")   # 0.5 % rounding tolerance


@dataclass(frozen=True)
class CoverEvent:
    line: CoverLineKind
    classification: str          # "underpayment" | "wrong_recipient" | "non_delivery"
    loss: Decimal                # positive amount to pay out
    loss_bearer: CoverLossBearerKind


def reconcile(
    expected_amount: float | None,
    executed_amount: float | None,
    expected_recipient: str | None,
    executed_recipient: str | None,
) -> CoverEvent | None:
    """Compare intent ground truth against what was actually executed.

    Returns a CoverEvent when a covered divergence is detected, else None.
    Priority: recipient mismatch > underpayment.
    """
    if expected_recipient and executed_recipient:
        if expected_recipient.strip() != executed_recipient.strip():
            loss = Decimal(str(executed_amount or 0)).quantize(Decimal("0.000001"))
            return CoverEvent(
                line=CoverLineKind.hallucination,
                classification="wrong_recipient",
                loss=loss,
                loss_bearer=CoverLossBearerKind.treasury,
            )

    if expected_amount is not None and executed_amount is not None:
        exp = Decimal(str(expected_amount))
        exe = Decimal(str(executed_amount))
        shortfall = (exp - exe).quantize(Decimal("0.000001"))
        relative = shortfall / exp if exp > 0 else Decimal("0")
        if shortfall > 0 and relative > _AMOUNT_TOLERANCE:
            return CoverEvent(
                line=CoverLineKind.hallucination,
                classification="underpayment",
                loss=shortfall,
                loss_bearer=CoverLossBearerKind.merchant,
            )

    return None


def non_delivery_event(executed_amount: float) -> CoverEvent:
    """Construct a non-delivery CoverEvent (merchant attests / maturity timer)."""
    return CoverEvent(
        line=CoverLineKind.non_delivery,
        classification="non_delivery",
        loss=Decimal(str(executed_amount)).quantize(Decimal("0.000001")),
        loss_bearer=CoverLossBearerKind.treasury,
    )
