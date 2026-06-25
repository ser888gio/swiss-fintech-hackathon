"""Scope policy — ARS G4 (Spend scope) guardrail.

Pure function, no I/O, all inputs passed in by the caller (which fetches the
current reservation total from the store atomically before calling this).

Money is Decimal throughout; the caller must convert from any float source
before calling. Spend caps use ROUND_DOWN semantics so rounding never silently
exceeds a limit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal

GLOBAL_AUTO_SETTLE_CEILING_USD = Decimal("500")


@dataclass(frozen=True)
class ScopeDecision:
    allowed: bool
    requires_approval: bool = False  # True = ESCALATE; False + not allowed = BLOCK
    rule_fired: str | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentScope:
    """Configuration block for a single agent's spending policy.

    All monetary fields are Decimal. The caller must build this from the config
    layer (which may store strings); convert at the boundary, not here.

    Allow/block semantics:
    - null (None) allowlist  = NO constraint (any value accepted)
    - empty [] allowlist     = explicit deny-all
    - block list overrides allow list
    """

    max_per_transaction: Decimal  # hard cap per single payment
    max_per_day: Decimal  # rolling 24h cap (committed + reserved)

    # Address-level allow/block
    allowed_addresses: list[str] | None = None
    blocked_addresses: list[str] = field(default_factory=list)

    # Host-level allow/block (used for x402 service payments)
    allowed_service_hosts: list[str] | None = None
    blocked_service_hosts: list[str] = field(default_factory=list)

    # Service type allowlist (x402)
    allowed_service_types: list[str] | None = None

    # Category allowlist (intent.purpose)
    allowed_categories: list[str] | None = None

    # Asset allowlist (e.g. ["RLUSD"])
    allowed_assets: list[str] | None = None

    # Network constraint (const "XRPL" for this project)
    allowed_network: str | None = None

    # Unknown merchant gate
    require_known_merchant: bool = False

    # Per-agent approval threshold (≤ GLOBAL_AUTO_SETTLE_CEILING_USD; enforced by form)
    requires_approval_above: Decimal | None = None

    # Global ceiling — no agent may auto-settle above this regardless of their config
    global_ceiling_usd: Decimal = GLOBAL_AUTO_SETTLE_CEILING_USD


_QUANTIZE = Decimal("0.000001")  # 6dp — matches RLUSD issued-currency precision


def evaluate_scope(
    spend: Decimal,
    scope: AgentScope,
    spent_today: Decimal,  # committed + reserved, fetched atomically by caller
    payee_address: str | None = None,
    service_host: str | None = None,
    service_type: str | None = None,
    asset: str | None = None,
    network: str | None = None,
    category: str | None = None,
    payee_is_known_merchant: bool = True,
) -> ScopeDecision:
    """Evaluate per-agent scope policy for a proposed payment.

    Returns ScopeDecision:
      allowed=True                           → ALLOW (auto-settle path)
      allowed=False, requires_approval=False → BLOCK (hard stop)
      allowed=False, requires_approval=True  → ESCALATE (Firefly approval)

    Policy ladder (from design doc):
      1.  Address/host blocklist, unknown merchant, asset/network violation → BLOCK
      2.  spend > max_per_transaction → BLOCK
      3.  spent_today + spend > max_per_day → BLOCK
      [4. AML/KYC handled by engine.evaluate(), not here]
      5.  spend > min(requires_approval_above, global_ceiling_usd) → ESCALATE
    """
    spend_q = spend.quantize(_QUANTIZE, rounding=ROUND_DOWN)
    spent_today_q = spent_today.quantize(_QUANTIZE, rounding=ROUND_DOWN)

    # ── Step 1: blocklist / allowlist / gate checks ────────────────────────────

    # 1a: address blocklist (block overrides allow)
    if (
        payee_address
        and scope.blocked_addresses
        and payee_address in scope.blocked_addresses
    ):
        return ScopeDecision(
            allowed=False,
            rule_fired="payee_on_blocklist",
            reasons=[f"payee {payee_address} is on the agent blocked-address list"],
        )

    # 1b: address allowlist (None = any; [] = deny-all)
    if payee_address and scope.allowed_addresses is not None:
        if payee_address not in scope.allowed_addresses:
            return ScopeDecision(
                allowed=False,
                rule_fired="payee_not_in_allowlist",
                reasons=[
                    f"payee {payee_address} is not in the agent allowed-address list"
                ],
            )

    # 1c: unknown merchant gate
    if scope.require_known_merchant and not payee_is_known_merchant:
        return ScopeDecision(
            allowed=False,
            rule_fired="unknown_merchant",
            reasons=["require_known_merchant is set but payee is not a known merchant"],
        )

    # 1d: asset allowlist
    if asset and scope.allowed_assets is not None:
        if asset.upper() not in [a.upper() for a in scope.allowed_assets]:
            return ScopeDecision(
                allowed=False,
                rule_fired="asset_not_allowed",
                reasons=[
                    f"asset '{asset}' not in allowed_assets {scope.allowed_assets}"
                ],
            )

    # 1e: network check
    if network and scope.allowed_network is not None:
        if network.upper() != scope.allowed_network.upper():
            return ScopeDecision(
                allowed=False,
                rule_fired="network_not_allowed",
                reasons=[
                    f"network '{network}' does not match allowed_network '{scope.allowed_network}'"
                ],
            )

    # 1f: service host blocklist
    if (
        service_host
        and scope.blocked_service_hosts
        and service_host in scope.blocked_service_hosts
    ):
        return ScopeDecision(
            allowed=False,
            rule_fired="host_on_blocklist",
            reasons=[
                f"service host '{service_host}' is on the agent blocked-host list"
            ],
        )

    # 1g: service host allowlist (None = any; [] = deny-all)
    if service_host and scope.allowed_service_hosts is not None:
        if service_host not in scope.allowed_service_hosts:
            return ScopeDecision(
                allowed=False,
                rule_fired="host_not_in_allowlist",
                reasons=[f"service host '{service_host}' not in allowed_service_hosts"],
            )

    # 1h: service type allowlist
    if service_type and scope.allowed_service_types is not None:
        if service_type not in scope.allowed_service_types:
            return ScopeDecision(
                allowed=False,
                rule_fired="service_type_not_allowed",
                reasons=[f"service type '{service_type}' not in allowed_service_types"],
            )

    # 1i: category allowlist
    if category and scope.allowed_categories is not None:
        if category not in scope.allowed_categories:
            return ScopeDecision(
                allowed=False,
                rule_fired="category_not_allowed",
                reasons=[
                    f"category '{category}' not in allowed_categories {scope.allowed_categories}"
                ],
            )

    # ── Step 2: per-transaction cap ────────────────────────────────────────────

    max_tx_q = scope.max_per_transaction.quantize(_QUANTIZE, rounding=ROUND_DOWN)
    if spend_q > max_tx_q:
        return ScopeDecision(
            allowed=False,
            rule_fired="scope_per_tx_exceeded",
            reasons=[f"spend {spend_q} exceeds per-transaction cap {max_tx_q}"],
        )

    # ── Step 3: per-day velocity cap ───────────────────────────────────────────

    max_day_q = scope.max_per_day.quantize(_QUANTIZE, rounding=ROUND_DOWN)
    projected = (spent_today_q + spend_q).quantize(_QUANTIZE, rounding=ROUND_DOWN)
    if projected > max_day_q:
        return ScopeDecision(
            allowed=False,
            rule_fired="scope_per_day_exceeded",
            reasons=[f"projected daily spend {projected} would exceed cap {max_day_q}"],
        )

    # ── Step 5: approval threshold / global ceiling (ESCALATE, not BLOCK) ──────

    approval_threshold = (
        min(scope.requires_approval_above, scope.global_ceiling_usd)
        if scope.requires_approval_above is not None
        else scope.global_ceiling_usd
    ).quantize(_QUANTIZE, rounding=ROUND_DOWN)

    if spend_q > approval_threshold:
        return ScopeDecision(
            allowed=False,
            requires_approval=True,
            rule_fired="approval_threshold_exceeded",
            reasons=[
                f"spend {spend_q} exceeds approval threshold {approval_threshold} "
                f"(GLOBAL_CEILING={scope.global_ceiling_usd})"
            ],
        )

    return ScopeDecision(allowed=True, rule_fired=None, reasons=[])
