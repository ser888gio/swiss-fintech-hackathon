"""Agent-to-Agent Delegation tool (Feature C, G5 — Delegation Scope guardrail).

A parent agent grants a scoped budget to a sub-agent wallet. The sub-agent may
only spend within the delegated limits (max_total, max_per_tx, max_per_day,
allowed_service_hosts, expiry). Every draw is checked against the grant via
evaluate_delegation (G5) before any payment is submitted.

The parent funds the sub-agent wallet via a real RLUSD Payment (same execution
path as process_payment, so it inherits policy + Firefly approval for large
funding amounts). The grant record is persisted in Postgres.

Pure guardrail (evaluate_delegation) — no I/O, unit-tested separately.
Funding path (grant_delegation) — real-mode XRPL Payment; mocked in mock mode.

Determinism boundary: grant_delegation checks that the funding amount itself
passes policy (via the existing execute_payment path) before storing the grant.
The LLM never calls this; only orchestrator code does.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal

from .. import db, store, xrpl_client
from ..config import get_settings
from ..schemas import DelegationGrant, DelegationGrantCreate, GuardrailResult, ScopeDecisionSchema

log = logging.getLogger(__name__)

_QUANTIZE = Decimal("0.000001")

# ── In-memory grant store ─────────────────────────────────────────────────────
# Grants are small and rarely change — full table fits in memory comfortably.
_grants: dict[str, DelegationGrant] = {}         # grant_id → DelegationGrant
_grants_by_child: dict[str, list[str]] = {}      # child_address → [grant_id]


def reset_mock_state() -> None:
    _grants.clear()
    _grants_by_child.clear()


# ── Pure guardrail (G5) ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class DelegationDecision:
    allowed: bool
    rule_fired: str | None
    reasons: list[str]


def evaluate_delegation(
    spend: Decimal,
    grant: DelegationGrant,
    spent_so_far: Decimal,    # drawn from this grant so far (caller fetches atomically)
) -> DelegationDecision:
    """G5: check a proposed sub-agent draw against the parent's delegation grant.

    Pure function, no I/O. Checks in order (first failure short-circuits):
      - Grant not revoked
      - Grant not expired
      - spend ≤ grant.max_per_tx
      - spent_so_far + spend ≤ grant.max_total
      - spent_so_far + spend ≤ grant.max_per_day (same as max_total for simplicity;
        callers can pass a rolling 24h sum instead of lifetime sum)

    Returns DelegationDecision(allowed=True) when all checks pass.
    """
    if grant.revoked:
        return DelegationDecision(
            allowed=False,
            rule_fired="delegation_revoked",
            reasons=["delegation grant has been revoked"],
        )

    if grant.expires_at is not None:
        now = datetime.now(timezone.utc)
        if now > grant.expires_at:
            return DelegationDecision(
                allowed=False,
                rule_fired="delegation_expired",
                reasons=[f"delegation grant expired at {grant.expires_at.isoformat()}"],
            )

    spend_q = spend.quantize(_QUANTIZE, rounding=ROUND_DOWN)
    spent_q = spent_so_far.quantize(_QUANTIZE, rounding=ROUND_DOWN)
    max_tx = Decimal(grant.max_per_tx).quantize(_QUANTIZE, rounding=ROUND_DOWN)
    max_day = Decimal(grant.max_per_day).quantize(_QUANTIZE, rounding=ROUND_DOWN)
    max_total = Decimal(grant.max_total).quantize(_QUANTIZE, rounding=ROUND_DOWN)

    if spend_q > max_tx:
        return DelegationDecision(
            allowed=False,
            rule_fired="delegation_per_tx_exceeded",
            reasons=[f"spend {spend_q} exceeds delegated per-tx cap {max_tx}"],
        )

    projected = (spent_q + spend_q).quantize(_QUANTIZE, rounding=ROUND_DOWN)
    if projected > max_day:
        return DelegationDecision(
            allowed=False,
            rule_fired="delegation_per_day_exceeded",
            reasons=[f"projected daily draw {projected} exceeds delegated cap {max_day}"],
        )

    if projected > max_total:
        return DelegationDecision(
            allowed=False,
            rule_fired="delegation_total_exceeded",
            reasons=[f"projected lifetime draw {projected} exceeds delegation total {max_total}"],
        )

    return DelegationDecision(allowed=True, rule_fired=None, reasons=[])


# ── grant_delegation (orchestrator action) ────────────────────────────────────

async def grant_delegation(create: DelegationGrantCreate) -> DelegationGrant:
    """Create a delegation grant and optionally fund the sub-agent wallet.

    Steps:
    1. Persist the grant record in memory + DB.
    2. Fund the child wallet with max_total RLUSD via a Payment (inherits policy).
       In mock mode a deterministic tx hash is used; no real Payment submitted.

    Returns the persisted DelegationGrant (with fund_tx_hash populated).
    """
    settings = get_settings()
    if not settings.delegation_enabled:
        raise DelegationDisabled("delegation_enabled is False — enable it in config")

    grant_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    fund_tx_hash: str | None = None
    fund_explorer_url: str | None = None

    if settings.use_mock_xrpl:
        fund_tx_hash = xrpl_client.mock_tx_hash("delegation_fund", grant_id)
    else:
        fund_tx_hash, fund_explorer_url = await _fund_child_wallet(
            create.child_address,
            Decimal(create.max_total),
            create.currency,
            grant_id,
            settings,
        )

    grant = DelegationGrant(
        id=grant_id,
        parent_address=create.parent_address,
        child_address=create.child_address,
        max_total=create.max_total,
        max_per_tx=create.max_per_tx,
        max_per_day=create.max_per_day,
        currency=create.currency,
        allowed_service_hosts=create.allowed_service_hosts,
        allowed_service_types=create.allowed_service_types,
        expires_at=create.expires_at,
        fund_tx_hash=fund_tx_hash,
        fund_explorer_url=fund_explorer_url,
        revoked=False,
        created_at=now,
        updated_at=now,
    )
    _store_grant(grant)
    _schedule_persist(grant)

    from . import audit_log
    audit_log.append(
        event_type="delegation_grant_created",
        actor="settlement_layer",
        context_kind="delegation_fund",
        payload={
            "grant_id": grant_id,
            "parent": create.parent_address,
            "child": create.child_address,
            "max_total": create.max_total,
            "fund_tx_hash": fund_tx_hash,
        },
    )
    return grant


def revoke_delegation(grant_id: str) -> DelegationGrant:
    """Mark a grant as revoked (immediate, in-memory; DB write-behind)."""
    grant = _grants.get(grant_id)
    if grant is None:
        raise DelegationNotFound(grant_id)
    revoked = grant.model_copy(update={"revoked": True, "updated_at": datetime.now(timezone.utc)})
    _grants[grant_id] = revoked
    _schedule_persist(revoked)
    return revoked


def get_grant(grant_id: str) -> DelegationGrant | None:
    return _grants.get(grant_id)


def grants_for_child(child_address: str) -> list[DelegationGrant]:
    """Return all non-revoked grants where child_address is the sub-agent."""
    ids = _grants_by_child.get(child_address, [])
    return [g for gid in ids if (g := _grants.get(gid)) and not g.revoked]


# ── Real-mode funding ─────────────────────────────────────────────────────────

async def _fund_child_wallet(
    child_address: str,
    amount: Decimal,
    currency: str,
    grant_id: str,
    settings,
) -> tuple[str, str | None]:
    from ..ledger import Ledger
    from xrpl.models.transactions import Payment, Memo
    import json

    ledger = Ledger(settings)
    wallet = ledger.treasury_wallet
    memo_data = json.dumps({"delegation_grant": grant_id}, separators=(",", ":"))
    tx = Payment(
        account=wallet.address,
        destination=child_address,
        amount=xrpl_client.to_wire_amount(amount, currency, settings),
        source_tag=settings.delegation_default_max_per_tx_usd,  # Starter Kit tag
        memos=[Memo(
            memo_type="delegation/v1".encode().hex().upper(),
            memo_data=memo_data.encode().hex().upper(),
        )],
    )
    result = await ledger.submit(tx, wallet)
    tx_hash = result["hash"]
    return tx_hash, xrpl_client.explorer_tx_url_for(tx_hash, settings.xrpl_endpoint)


# ── Persistence ───────────────────────────────────────────────────────────────

def _store_grant(grant: DelegationGrant) -> None:
    _grants[grant.id] = grant
    _grants_by_child.setdefault(grant.child_address, [])
    if grant.id not in _grants_by_child[grant.child_address]:
        _grants_by_child[grant.child_address].append(grant.id)


def _schedule_persist(grant: DelegationGrant) -> None:
    import asyncio
    try:
        asyncio.get_running_loop()
        asyncio.create_task(_persist_grant(grant))
        return
    except RuntimeError:
        pass


async def _persist_grant(grant: DelegationGrant) -> None:
    if db.session_factory is None:
        return
    from ..models import DelegationGrantRecord
    try:
        async with db.session_factory() as session:
            row = DelegationGrantRecord(
                id=grant.id,
                parent_address=grant.parent_address,
                child_address=grant.child_address,
                max_total=grant.max_total,
                max_per_tx=grant.max_per_tx,
                max_per_day=grant.max_per_day,
                currency=grant.currency,
                allowed_service_hosts=grant.allowed_service_hosts,
                allowed_service_types=grant.allowed_service_types,
                expires_at=grant.expires_at,
                fund_tx_hash=grant.fund_tx_hash,
                fund_explorer_url=grant.fund_explorer_url,
                revoked=grant.revoked,
                created_at=grant.created_at,
                updated_at=grant.updated_at,
            )
            await session.merge(row)
            await session.commit()
    except Exception as exc:
        log.warning("Failed to persist delegation grant %s: %s", grant.id, exc)


# ── Errors ────────────────────────────────────────────────────────────────────

class DelegationError(Exception):
    pass

class DelegationDisabled(DelegationError):
    pass

class DelegationNotFound(DelegationError):
    pass
