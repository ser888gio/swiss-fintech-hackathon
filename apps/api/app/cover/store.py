"""In-memory store for Cover policies, payouts, reservations, and risk posteriors.

Capacity reservation is atomic (same thread in the async event loop):
  bind()  → reserve(policy_id, cover_cap)
  claim() → reduce reservation by payout amount; exhausted policies release fully
  expire()→ release reservation
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from ..insurance import risk as ins_risk
from ..insurance.risk import AgentRisk
from ..schemas import CoverLineKind, CoverPolicy, CoverPolicyStatus, CoverPayout

log = logging.getLogger(__name__)

_policies: dict[str, CoverPolicy] = {}
_payouts: list[CoverPayout] = []
_claimed_payments: set[str] = set()          # payment_id → already claimed (replay guard)
_agent_risk: dict[str, AgentRisk] = {}
_bands: dict[str, str] = {}
_reservations: dict[str, Decimal] = {}       # policy_id → reserved cover_cap
_pool = {"premiums": Decimal("0"), "claims": Decimal("0")}


def reset_mock_state() -> None:
    _policies.clear()
    _payouts.clear()
    _claimed_payments.clear()
    _agent_risk.clear()
    _bands.clear()
    _reservations.clear()
    _pool["premiums"] = Decimal("0")
    _pool["claims"] = Decimal("0")


# ── Capacity accounting ───────────────────────────────────────────────────────

def reserved_capacity() -> Decimal:
    """Total cover_cap reserved by all active (non-exhausted/expired) policies."""
    return sum(_reservations.values(), Decimal("0"))


def free_capacity(first_loss_usd: float) -> Decimal:
    fl = Decimal(str(first_loss_usd)) + _pool["premiums"] - _pool["claims"]
    return max(Decimal("0"), fl - reserved_capacity())


def reserve(policy_id: str, cover_cap: Decimal) -> None:
    _reservations[policy_id] = cover_cap


def release_reservation(policy_id: str) -> None:
    _reservations.pop(policy_id, None)


# ── Agent risk posterior ──────────────────────────────────────────────────────

def get_or_seed_risk(agent_address: str, score_band: str) -> AgentRisk:
    r = _agent_risk.get(agent_address)
    if r is None:
        r = ins_risk.from_band(score_band)
        _agent_risk[agent_address] = r
        _bands[agent_address] = score_band
    return r


def record_default(agent_address: str, loss: Decimal, tau_days: float) -> AgentRisk:
    from ..config import get_settings
    settings = get_settings()
    r = get_or_seed_risk(agent_address, _bands.get(agent_address, "STANDARD"))
    ref = Decimal(str(settings.policy_threshold_usd or 10_000))
    weight = max(0.25, min(4.0, float(loss / ref)))
    updated = ins_risk.update(r, defaulted=True, exposure_weight=weight, tau_days=tau_days)
    _agent_risk[agent_address] = updated
    return updated


def get_agent_risk_snapshot(agent_address: str) -> dict | None:
    r = _agent_risk.get(agent_address)
    if r is None:
        return None
    return {
        "agent_address": agent_address,
        "score_band": _bands.get(agent_address, "STANDARD"),
        "alpha": round(r.alpha, 6),
        "beta": round(r.beta, 6),
        "pd": round(ins_risk.pd_agent(r), 6),
        "credibility": round(ins_risk.credibility(r), 6),
    }


# ── Policies ──────────────────────────────────────────────────────────────────

def save_policy(policy: CoverPolicy) -> CoverPolicy:
    _policies[policy.id] = policy
    return policy


def get_policy(policy_id: str) -> CoverPolicy | None:
    _expire_stale()
    return _policies.get(policy_id)


def list_policies(agent_address: str | None = None) -> list[CoverPolicy]:
    _expire_stale()
    policies = list(_policies.values())
    if agent_address:
        policies = [p for p in policies if p.agent_address == agent_address]
    return sorted(policies, key=lambda p: p.created_at, reverse=True)


def cancel_policy(policy_id: str) -> None:
    """Mark a policy as cancelled and release its reservation — demo use only."""
    now = datetime.now(timezone.utc)
    policy = _policies.get(policy_id)
    if policy and policy.status == CoverPolicyStatus.active:
        _policies[policy_id] = policy.model_copy(
            update={"status": CoverPolicyStatus.cancelled, "updated_at": now}
        )
        release_reservation(policy_id)


def _expire_stale() -> None:
    now = datetime.now(timezone.utc)
    for policy in list(_policies.values()):
        if policy.status == CoverPolicyStatus.active and now > policy.period_end:
            _policies[policy.id] = policy.model_copy(
                update={"status": CoverPolicyStatus.expired, "updated_at": now}
            )
            release_reservation(policy.id)


# ── Replay guard ──────────────────────────────────────────────────────────────

def is_claimed(payment_id: str) -> bool:
    return payment_id in _claimed_payments


def mark_claimed(payment_id: str) -> None:
    _claimed_payments.add(payment_id)


# ── Payouts ───────────────────────────────────────────────────────────────────

def save_payout(payout: CoverPayout) -> CoverPayout:
    _payouts.append(payout)
    return payout


def list_payouts(policy_id: str | None = None) -> list[CoverPayout]:
    results = list(_payouts)
    if policy_id:
        results = [p for p in results if p.policy_id == policy_id]
    return sorted(results, key=lambda p: p.created_at, reverse=True)


def payout_count_for_pair(agent_address: str, merchant: str) -> int:
    """Collusion guard: count claims from agent against this merchant across all policies."""
    agent_policy_ids = {p.id for p in _policies.values() if p.agent_address == agent_address}
    return sum(
        1 for p in _payouts
        if p.policy_id in agent_policy_ids and p.destination == merchant
    )


def reset_pair_payouts(agent_address: str, merchant: str) -> None:
    """Remove stored payouts for one agent↔merchant pair — used by demo reset only."""
    agent_policy_ids = {p.id for p in _policies.values() if p.agent_address == agent_address}
    _payouts[:] = [
        p for p in _payouts
        if not (p.policy_id in agent_policy_ids and p.destination == merchant)
    ]


# ── Pool accounting ───────────────────────────────────────────────────────────

def add_premium(amount: Decimal) -> None:
    _pool["premiums"] += amount


def add_claim(amount: Decimal) -> None:
    _pool["claims"] += amount


def pool_stats(first_loss_usd: float) -> dict:
    _expire_stale()
    active = [p for p in _policies.values() if p.status == CoverPolicyStatus.active]
    # Keep the accounting type stable even when there are no active policies.
    # sum() defaults to the integer 0 for an empty iterable, which later breaks
    # Decimal-only formatting such as quantize().
    cover_in_force = sum((Decimal(p.cover_cap) for p in active), Decimal("0"))
    fl = Decimal(str(first_loss_usd)) + _pool["premiums"] - _pool["claims"]
    first_loss = max(Decimal("0"), fl)
    res = reserved_capacity()
    free = max(Decimal("0"), first_loss - res)
    ratio = float(free / first_loss) if first_loss > 0 else 0.0
    return {
        "first_loss": first_loss,
        "reserved": res,
        "free_capacity": free,
        "premiums": _pool["premiums"],
        "claims": _pool["claims"],
        "policies_active": len(active),
        "cover_in_force": cover_in_force,
        "capacity_ratio": ratio,
    }
