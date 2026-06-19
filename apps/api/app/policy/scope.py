"""Scope policy — ARS G4 (Spend scope) guardrail.

Pure function, no I/O, all inputs passed in by the caller (which fetches the
current reservation total from the store atomically before calling this).

Money is Decimal throughout; the caller must convert from any float source
before calling. Spend caps use ROUND_DOWN semantics so rounding never silently
exceeds a limit.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal


@dataclass(frozen=True)
class ScopeDecision:
    allowed: bool
    rule_fired: str | None      # None when allowed
    reasons: list[str]


@dataclass(frozen=True)
class AgentScope:
    """Configuration block for a single agent's spending policy.

    All monetary fields are Decimal. The caller must build this from the config
    layer (which may store floats); convert at the boundary, not here.
    """

    max_per_transaction: Decimal   # hard cap per single payment
    max_per_day: Decimal           # rolling 24h cap (committed + reserved)
    allowed_service_hosts: list[str] | None = None  # None = any host allowed
    allowed_service_types: list[str] | None = None  # None = any type allowed


_QUANTIZE = Decimal("0.000001")  # 6dp — matches RLUSD issued-currency precision


def evaluate_scope(
    spend: Decimal,
    scope: AgentScope,
    spent_today: Decimal,       # committed + outstanding reservations, fetched atomically
    service_host: str | None = None,
    service_type: str | None = None,
) -> ScopeDecision:
    """G4: check a proposed spend against the agent's scope policy.

    Returns ScopeDecision(allowed=True) iff ALL of:
      - spend ≤ max_per_transaction (exact, ROUND_DOWN)
      - spent_today + spend ≤ max_per_day (exact, ROUND_DOWN)
      - service_host is in allowed_service_hosts (if the list is configured)
      - service_type is in allowed_service_types (if the list is configured)

    First failure short-circuits; all failing reasons are accumulated only when
    all checks must be reported. Returns the first blocking reason only (caller
    logs the trail).
    """
    spend_q = spend.quantize(_QUANTIZE, rounding=ROUND_DOWN)
    spent_today_q = spent_today.quantize(_QUANTIZE, rounding=ROUND_DOWN)
    max_tx_q = scope.max_per_transaction.quantize(_QUANTIZE, rounding=ROUND_DOWN)
    max_day_q = scope.max_per_day.quantize(_QUANTIZE, rounding=ROUND_DOWN)

    # G4a: per-transaction cap
    if spend_q > max_tx_q:
        return ScopeDecision(
            allowed=False,
            rule_fired="scope_per_tx_exceeded",
            reasons=[
                f"spend {spend_q} exceeds per-transaction cap {max_tx_q}"
            ],
        )

    # G4b: per-day velocity cap (atomic total from caller)
    projected = (spent_today_q + spend_q).quantize(_QUANTIZE, rounding=ROUND_DOWN)
    if projected > max_day_q:
        return ScopeDecision(
            allowed=False,
            rule_fired="scope_per_day_exceeded",
            reasons=[
                f"projected daily spend {projected} would exceed cap {max_day_q}"
            ],
        )

    # G4c: service host allowlist
    if scope.allowed_service_hosts is not None and service_host is not None:
        if service_host not in scope.allowed_service_hosts:
            return ScopeDecision(
                allowed=False,
                rule_fired="scope_host_not_allowed",
                reasons=[
                    f"service host '{service_host}' not in allowed list"
                ],
            )

    # G4d: service type allowlist
    if scope.allowed_service_types is not None and service_type is not None:
        if service_type not in scope.allowed_service_types:
            return ScopeDecision(
                allowed=False,
                rule_fired="scope_type_not_allowed",
                reasons=[
                    f"service type '{service_type}' not in allowed list"
                ],
            )

    return ScopeDecision(allowed=True, rule_fired=None, reasons=[])
