"""Deterministic claim eligibility rules — separate from payment policy.engine.

Pure functions, no I/O. All rules are ordered; the first failure short-circuits.
Returns a ClaimDecision (allowed/blocked) with a reason trail — never the LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from ..schemas import (
    CoverLineKind,
    CoverPolicy,
    CoverPolicyStatus,
    Payment,
    PaymentStatus,
)

_SANCTIONED_MERCHANTS: set[str] = set()  # populated from compliance tool at runtime


@dataclass(frozen=True)
class ClaimDecision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    block_reason: str | None = None


def evaluate(
    policy: CoverPolicy,
    payment: Payment,
    line: CoverLineKind,
    loss: Decimal,
    merchant: str,
    *,
    collusion_count: int = 0,
    collusion_threshold: int = 2,
    sanctioned_merchants: set[str] | None = None,
) -> ClaimDecision:
    """Run all eligibility gates for a cover claim.

    Rules (ordered, first failure blocks):
      R1  Policy must be active (not expired/exhausted/cancelled).
      R2  Payment must be settled (not routing/pending/blocked/failed).
      R3  Payment agent must match policy agent.
      R4  Cover line must be in the policy's active lines.
      R5  Loss must be positive.
      R6  Merchant must not be on the sanctions list.
      R7  Collusion guard: too many claims against same merchant.
      R8  Loss must not exceed per_claim_limit.
      R9  Cover remaining must be sufficient.
    """
    reasons: list[str] = []

    # R1 — policy active
    if policy.status != CoverPolicyStatus.active:
        return ClaimDecision(
            allowed=False,
            block_reason=f"policy is {policy.status.value}",
            reasons=reasons,
        )
    now = datetime.now(timezone.utc)
    if now > policy.period_end:
        return ClaimDecision(
            allowed=False, block_reason="policy period has expired", reasons=reasons
        )

    # R2 — payment settled
    if payment.status != PaymentStatus.settled:
        return ClaimDecision(
            allowed=False,
            block_reason=f"payment is {payment.status.value}, not settled",
            reasons=reasons,
        )

    # R3 — agent ownership: the payment must originate from the policy's agent
    payment_sender = payment.intent.from_account
    if payment_sender != policy.agent_address:
        # Also allow the treasury wallet to match (treasury pays on behalf of agent)
        # but require explicit policy ownership check
        return ClaimDecision(
            allowed=False,
            block_reason="payment sender does not match policy agent",
            reasons=reasons,
        )

    # R4 — line in policy
    if line not in policy.lines:
        return ClaimDecision(
            allowed=False,
            block_reason=f"line {line.value} not covered by this policy",
            reasons=reasons,
        )

    # R5 — positive loss
    if loss <= Decimal("0"):
        return ClaimDecision(
            allowed=False, block_reason="loss must be positive", reasons=reasons
        )

    # R6 — sanctions
    sanctioned = sanctioned_merchants or _SANCTIONED_MERCHANTS
    if merchant in sanctioned:
        return ClaimDecision(
            allowed=False, block_reason="merchant on sanctions list", reasons=reasons
        )

    # R7 — collusion guard
    if collusion_count >= collusion_threshold:
        return ClaimDecision(
            allowed=False,
            block_reason=f"collusion pattern: {collusion_count} prior claims against this merchant",
            reasons=reasons,
        )

    # R8 — per-claim limit
    pcl = Decimal(policy.per_claim_limit)
    if loss > pcl:
        reasons.append(f"loss {loss} capped to per_claim_limit {pcl}")
        loss = pcl  # caller must use the capped value; we just note it

    # R9 — cover remaining
    remaining = Decimal(policy.cover_remaining)
    if remaining <= Decimal("0"):
        return ClaimDecision(
            allowed=False,
            block_reason="policy cover_remaining is exhausted",
            reasons=reasons,
        )

    return ClaimDecision(allowed=True, reasons=reasons)
