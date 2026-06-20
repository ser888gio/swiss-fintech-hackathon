"""Tests for tools/delegation.py — G5 (Delegation Scope) guardrail.

All pure-function tests use evaluate_delegation directly (no I/O, no DB, no
network). grant_delegation / revoke_delegation tests use mock mode and reset
state between runs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.schemas import DelegationGrant, DelegationGrantCreate
from app.tools.delegation import (
    DelegationDecision,
    DelegationDisabled,
    DelegationNotFound,
    evaluate_delegation,
    get_grant,
    grants_for_child,
    grant_delegation,
    reset_mock_state,
    revoke_delegation,
)


@pytest.mark.asyncio
async def test_route_rejects_blank_delegation_addresses() -> None:
    from app.routes.treasury import create_delegation

    create = DelegationGrantCreate(
        parent_address="   ",
        child_address="",
        max_total="500.000000",
        max_per_tx="50.000000",
        max_per_day="200.000000",
        currency="RLUSD",
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_delegation(create)

    assert exc_info.value.status_code == 400
    assert "must not be blank" in str(exc_info.value.detail)


_NOW = datetime(2026, 6, 19, 12, 0, 0, tzinfo=timezone.utc)


def _make_grant(**overrides) -> DelegationGrant:
    base = dict(
        id="grant-1",
        parent_address="rPARENT0000000000000000000000000000",
        child_address="rCHILD00000000000000000000000000000",
        max_total="500",
        max_per_tx="100.000000",
        max_per_day="250",
        currency="RLUSD",
        allowed_service_hosts=None,
        allowed_service_types=None,
        expires_at=None,
        fund_tx_hash=None,
        fund_explorer_url=None,
        revoked=False,
        created_at=_NOW,
        updated_at=_NOW,
    )
    base.update(overrides)
    return DelegationGrant(**base)


# ── Revoked grant ─────────────────────────────────────────────────────────────

def test_revoked_grant_is_blocked():
    grant = _make_grant(revoked=True)
    result = evaluate_delegation(Decimal("50"), grant, Decimal("0"))
    assert result.allowed is False
    assert result.rule_fired == "delegation_revoked"


# ── Expired grant ─────────────────────────────────────────────────────────────

def test_expired_grant_is_blocked():
    past = datetime(2025, 1, 1, tzinfo=timezone.utc)
    grant = _make_grant(expires_at=past)
    result = evaluate_delegation(Decimal("50"), grant, Decimal("0"))
    assert result.allowed is False
    assert result.rule_fired == "delegation_expired"


def test_future_expiry_passes():
    future = datetime(2027, 1, 1, tzinfo=timezone.utc)
    grant = _make_grant(expires_at=future)
    result = evaluate_delegation(Decimal("50"), grant, Decimal("0"))
    assert result.allowed is True


def test_no_expiry_never_expires():
    grant = _make_grant(expires_at=None)
    result = evaluate_delegation(Decimal("50"), grant, Decimal("0"))
    assert result.allowed is True


# ── Per-transaction cap ───────────────────────────────────────────────────────

def test_within_per_tx_cap_allowed():
    grant = _make_grant()
    result = evaluate_delegation(Decimal("100"), grant, Decimal("0"))
    assert result.allowed is True


def test_exactly_at_per_tx_cap_allowed():
    grant = _make_grant()
    result = evaluate_delegation(Decimal("100.000000"), grant, Decimal("0"))
    assert result.allowed is True


def test_over_per_tx_cap_blocked():
    grant = _make_grant()
    result = evaluate_delegation(Decimal("100.000001"), grant, Decimal("0"))
    assert result.allowed is False
    assert result.rule_fired == "delegation_per_tx_exceeded"
    assert result.reasons


# ── Per-day cap ───────────────────────────────────────────────────────────────

def test_within_per_day_cap_allowed():
    grant = _make_grant()
    result = evaluate_delegation(Decimal("50"), grant, Decimal("200"))
    assert result.allowed is True


def test_at_per_day_cap_allowed():
    grant = _make_grant()
    result = evaluate_delegation(Decimal("50"), grant, Decimal("200"))
    assert result.allowed is True


def test_over_per_day_cap_blocked():
    grant = _make_grant()
    result = evaluate_delegation(Decimal("50.000001"), grant, Decimal("200"))
    assert result.allowed is False
    assert result.rule_fired == "delegation_per_day_exceeded"


# ── Lifetime total cap ────────────────────────────────────────────────────────

def test_within_total_cap_allowed():
    # max_per_day=250, max_total=1000: spend 100 with 100 already drawn (total=200, day=200)
    grant = _make_grant()
    result = evaluate_delegation(Decimal("100"), grant, Decimal("100"))
    assert result.allowed is True


def test_over_total_cap_blocked():
    grant = _make_grant()
    # max_per_day is 250, max_total is 1000; spend 100 on top of 950 → total 1050 > 1000
    # But per-day check: 950 + 100 = 1050 > 250, so per-day fires first.
    # Use small day sum to isolate total cap:
    result = evaluate_delegation(Decimal("100"), grant, Decimal("950"))
    # 950 + 100 = 1050 > 1000 (total) AND > 250 (day) — per_day fires first
    assert result.allowed is False
    # Either per_day or total — both correctly block; just confirm it's blocked.
    assert result.rule_fired in ("delegation_per_day_exceeded", "delegation_total_exceeded")


def test_total_cap_exceeded_when_day_cap_is_higher():
    # Grant where max_per_day > max_total so we can isolate the total cap check.
    grant = _make_grant(max_per_day="2000.000000", max_total="500.000000", max_per_tx="200.000000")
    result = evaluate_delegation(Decimal("100"), grant, Decimal("450"))
    assert result.allowed is False
    assert result.rule_fired == "delegation_total_exceeded"


# ── Ordering: revoked before expired before caps ──────────────────────────────

def test_revoked_fires_before_expired():
    past = datetime(2025, 1, 1, tzinfo=timezone.utc)
    grant = _make_grant(revoked=True, expires_at=past)
    result = evaluate_delegation(Decimal("1"), grant, Decimal("0"))
    assert result.rule_fired == "delegation_revoked"


def test_expired_fires_before_per_tx():
    past = datetime(2025, 1, 1, tzinfo=timezone.utc)
    grant = _make_grant(expires_at=past)
    # spend way over cap, but expiry should fire first
    result = evaluate_delegation(Decimal("9999"), grant, Decimal("0"))
    assert result.rule_fired == "delegation_expired"


# ── Allowed result shape ──────────────────────────────────────────────────────

def test_allowed_result_has_no_rule_fired():
    grant = _make_grant()
    result = evaluate_delegation(Decimal("10"), grant, Decimal("0"))
    assert isinstance(result, DelegationDecision)
    assert result.rule_fired is None
    assert result.reasons == []


def test_blocked_result_has_reasons():
    grant = _make_grant(revoked=True)
    result = evaluate_delegation(Decimal("10"), grant, Decimal("0"))
    assert result.reasons


# ── grant_delegation (mock mode) ──────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset():
    reset_mock_state()
    yield
    reset_mock_state()


@pytest.mark.asyncio
async def test_grant_delegation_disabled(monkeypatch):
    import app.tools.delegation as mod
    from app.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "delegation_enabled", False, raising=False)
    import app.config as cfg
    cfg.get_settings.cache_clear()
    # Re-patch to avoid lru_cache returning the old object
    # Simpler: patch the attribute directly on the Settings object
    # Use the monkeypatched settings via dependency injection approach:
    with pytest.raises(DelegationDisabled):
        # Force the function to see delegation_enabled=False by patching get_settings
        original = mod.get_settings
        mod_settings = type("S", (), {"delegation_enabled": False, "use_mock_xrpl": True})()
        import app.tools.delegation as d
        old = d.get_settings
        d.get_settings = lambda: mod_settings
        try:
            create = DelegationGrantCreate(
                parent_address="rP",
                child_address="rC",
                max_total="100",
                max_per_tx="10",
                max_per_day="50",
            )
            await grant_delegation(create)
        finally:
            d.get_settings = old


@pytest.mark.asyncio
async def test_grant_delegation_mock(monkeypatch):
    import app.tools.delegation as d
    from app.config import Settings

    mock_settings = Settings(
        delegation_enabled=True,
        use_mock_xrpl=True,
        treasury_wallet_seed="",
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/treasury",
    )
    d.get_settings = lambda: mock_settings

    create = DelegationGrantCreate(
        parent_address="rPARENT",
        child_address="rCHILD",
        max_total="500",
        max_per_tx="50",
        max_per_day="200",
    )
    grant = await grant_delegation(create)

    assert grant.parent_address == "rPARENT"
    assert grant.child_address == "rCHILD"
    assert grant.fund_tx_hash is not None
    assert not grant.revoked

    # Retrievable
    fetched = get_grant(grant.id)
    assert fetched is not None
    assert fetched.id == grant.id

    # Listed under child
    child_grants = grants_for_child("rCHILD")
    assert any(g.id == grant.id for g in child_grants)

    # Restore
    from app.config import get_settings as real_get_settings
    d.get_settings = real_get_settings


@pytest.mark.asyncio
async def test_revoke_delegation_mock(monkeypatch):
    import app.tools.delegation as d
    from app.config import Settings

    mock_settings = Settings(
        delegation_enabled=True,
        use_mock_xrpl=True,
        treasury_wallet_seed="",
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/treasury",
    )
    d.get_settings = lambda: mock_settings

    create = DelegationGrantCreate(
        parent_address="rP2",
        child_address="rC2",
        max_total="100",
        max_per_tx="10",
        max_per_day="50",
    )
    grant = await grant_delegation(create)
    revoked = revoke_delegation(grant.id)
    assert revoked.revoked is True

    # G5 now blocks
    result = evaluate_delegation(Decimal("5"), revoked, Decimal("0"))
    assert result.allowed is False
    assert result.rule_fired == "delegation_revoked"

    from app.config import get_settings as real_get_settings
    d.get_settings = real_get_settings


def test_revoke_nonexistent_raises():
    with pytest.raises(DelegationNotFound):
        revoke_delegation("does-not-exist")


def test_no_grants_for_unknown_child():
    assert grants_for_child("rNOBODY") == []
