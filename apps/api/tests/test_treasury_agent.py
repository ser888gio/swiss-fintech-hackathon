"""Tests for the autonomous treasury agent.

Covers:
  evaluate_goal() — the core deterministic trigger (pure, no I/O).
  run() — full cycle with mocked orchestrator, verifying invariants:
    - LLM is never called as the decision-maker (only narration).
    - Only triggered goals produce payments.
    - last_triggered_at is updated only on fired goals.
    - Orchestrator errors skip the goal without crashing the run.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.agents import treasury_agent
from app.schemas import (
    Payment,
    PaymentIntent,
    PaymentStatus,
    PolicyDecision,
    TreasuryGoal,
    TreasuryGoalCreate,
    ReceiverEntityType,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _settings(**overrides):
    data = {
        "agent_max_amount_usd": 50_000.0,
        "agent_enabled": True,
        "agent_sender_country": "CH",
        "treasury_wallet_seed": "",
        "use_mock_xrpl": True,
        "openai_api_key": "",  # no LLM calls in tests
        "openai_model": "gpt-4o",
        "token_currency": "USD",
        "token_issuer_address": "",
        "policy_threshold_usd": 10_000.0,
        "policy_compliance_flag_score": 60,
        "route_slippage_bps": 50,
        "route_partial_payment": False,
        "credential_kyc_enabled": False,
        "credential_type": "KYC",
        "credential_issuer_address": "",
        "credential_issuer_seed": "",
        "credential_subject_seed": "",
        "public_intel_enabled": False,
        "opensanctions_api_key": "",
        "opensanctions_base_url": "",
        "opensanctions_dataset": "sanctions",
        "opensanctions_match_threshold": 0.85,
        "frankfurter_base_url": "https://api.frankfurter.dev/v1",
        "firefly_public_key": "",
        # XLS-65 vault — disabled by default in agent tests
        "vault_enabled": False,
        "vault_xrpl_endpoint": "wss://s.devnet.rippletest.net:51233",
        "vault_sweep_threshold_usd": 5_000.0,
        "vault_recall_threshold_usd": 1_000.0,
        "vault_id": "",
        # XLS-33 MPTokens — disabled by default in agent tests
        "mpt_enabled": False,
        "mpt_xrpl_endpoint": "",
        "mpt_issuance_id": "",
        "mpt_recipient_address": "",
        "mpt_recipient_seed": "",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _goal(**overrides) -> TreasuryGoal:
    data = {
        "id": "goal-001",
        "name": "Monthly supplier payment",
        "enabled": True,
        "beneficiary_name": "Acme Supplies AG",
        "beneficiary_address": "rReceiver",
        "beneficiary_country": "US",
        "receiver_entity_type": ReceiverEntityType.company,
        "amount": 1_000.0,
        "currency": "USD",
        "reference": "INV-AUTO-001",
        "purpose": "supplier_payment",
        "trigger_interval_hours": 720.0,  # 30 days
        "last_triggered_at": None,
    }
    data.update(overrides)
    return TreasuryGoal(**data)


def _patch_settings(monkeypatch, **overrides):
    s = _settings(**overrides)
    import app.agents.treasury_agent as ta
    import app.agents.orchestrator as orch
    import app.tools.routing as routing
    import app.tools.compliance as compliance
    import app.tools.credentials as creds
    import app.tools.audit as audit
    import app.tools.mptoken as mpt
    monkeypatch.setattr(ta, "get_settings", lambda: s)
    monkeypatch.setattr(orch, "get_settings", lambda: s)
    monkeypatch.setattr(routing, "get_settings", lambda: s)
    monkeypatch.setattr(compliance, "get_settings", lambda: s)
    monkeypatch.setattr(creds, "get_settings", lambda: s)
    monkeypatch.setattr(audit, "get_settings", lambda: s)
    monkeypatch.setattr(mpt, "get_settings", lambda: s)


# ── evaluate_goal (pure, no I/O) ──────────────────────────────────────────────

def test_disabled_goal_never_fires():
    fire, reason = treasury_agent.evaluate_goal(_goal(enabled=False), _now(), 50_000.0)
    assert fire is False
    assert "disabled" in reason


def test_amount_over_cap_skipped():
    fire, reason = treasury_agent.evaluate_goal(_goal(amount=60_000.0), _now(), 50_000.0)
    assert fire is False
    assert "cap" in reason.lower()


def test_never_triggered_fires_on_first_cycle():
    goal = _goal(last_triggered_at=None)
    fire, reason = treasury_agent.evaluate_goal(goal, _now(), 50_000.0)
    assert fire is True
    assert "never" in reason.lower()


def test_interval_elapsed_fires():
    last = _now() - timedelta(hours=721)
    goal = _goal(trigger_interval_hours=720.0, last_triggered_at=last)
    fire, reason = treasury_agent.evaluate_goal(goal, _now(), 50_000.0)
    assert fire is True
    assert "elapsed" in reason.lower()


def test_interval_not_elapsed_defers():
    last = _now() - timedelta(hours=100)
    goal = _goal(trigger_interval_hours=720.0, last_triggered_at=last)
    fire, reason = treasury_agent.evaluate_goal(goal, _now(), 50_000.0)
    assert fire is False
    assert "remaining" in reason.lower()


def test_exactly_at_interval_fires():
    last = _now() - timedelta(hours=720.0)
    goal = _goal(trigger_interval_hours=720.0, last_triggered_at=last)
    fire, _ = treasury_agent.evaluate_goal(goal, _now(), 50_000.0)
    assert fire is True


# ── run() with mocked orchestrator ────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_agent_state():
    """Isolate each test: clear goals and runs."""
    treasury_agent._goals.clear()
    treasury_agent._runs.clear()
    yield
    treasury_agent._goals.clear()
    treasury_agent._runs.clear()


async def test_run_fires_eligible_goal(monkeypatch):
    _patch_settings(monkeypatch)
    goal = treasury_agent.add_goal(_goal(last_triggered_at=None))

    run = await treasury_agent.run()

    assert run.goals_evaluated == 1
    assert run.goals_triggered == 1
    assert len(run.payments_initiated) == 1
    assert run.payments_skipped == []
    assert run.status == "completed"
    # last_triggered_at must be updated on the stored goal
    stored = treasury_agent.get_goal(goal.id)
    assert stored.last_triggered_at is not None


async def test_run_defers_goal_within_interval(monkeypatch):
    _patch_settings(monkeypatch)
    recent = _now() - timedelta(hours=1)
    treasury_agent.add_goal(_goal(trigger_interval_hours=720.0, last_triggered_at=recent))

    run = await treasury_agent.run()

    assert run.goals_triggered == 0
    assert len(run.payments_skipped) == 1
    assert len(run.payments_initiated) == 0


async def test_run_skips_disabled_goal(monkeypatch):
    _patch_settings(monkeypatch)
    treasury_agent.add_goal(_goal(enabled=False))

    run = await treasury_agent.run()

    assert run.goals_triggered == 0


async def test_run_skips_goal_over_cap(monkeypatch):
    _patch_settings(monkeypatch)
    treasury_agent.add_goal(_goal(amount=99_999.0))

    run = await treasury_agent.run()

    assert run.goals_triggered == 0
    assert any("cap" in line.lower() for line in run.trigger_log)


async def test_run_mixed_goals(monkeypatch):
    _patch_settings(monkeypatch)
    # eligible: never triggered
    treasury_agent.add_goal(_goal(id="g1", name="Due", last_triggered_at=None))
    # deferred: triggered 1h ago, 720h interval
    recent = _now() - timedelta(hours=1)
    treasury_agent.add_goal(_goal(id="g2", name="Not Due", last_triggered_at=recent, trigger_interval_hours=720.0))

    run = await treasury_agent.run()

    assert run.goals_evaluated == 2
    assert run.goals_triggered == 1
    assert len(run.payments_initiated) == 1
    assert len(run.payments_skipped) == 1


async def test_run_has_trigger_log_entry_per_goal(monkeypatch):
    _patch_settings(monkeypatch)
    treasury_agent.add_goal(_goal(id="g1", name="Alpha"))
    treasury_agent.add_goal(_goal(id="g2", name="Beta", enabled=False))

    run = await treasury_agent.run()

    # Each goal produces at least one log line; fired goals produce a second line.
    assert any("Alpha" in line for line in run.trigger_log)
    assert any("Beta" in line for line in run.trigger_log)


async def test_orchestrator_error_skips_goal_without_crashing(monkeypatch):
    _patch_settings(monkeypatch)
    treasury_agent.add_goal(_goal(last_triggered_at=None))

    async def boom(intent):
        raise RuntimeError("network error")

    monkeypatch.setattr(treasury_agent.orchestrator, "process_payment", boom)

    run = await treasury_agent.run()

    # Run completes; the goal is counted as skipped (not triggered).
    assert run.status == "completed"
    assert run.goals_triggered == 0
    assert any("failed" in line for line in run.trigger_log)


async def test_narration_is_deterministic_without_openai(monkeypatch):
    _patch_settings(monkeypatch)
    treasury_agent.add_goal(_goal(last_triggered_at=None))

    run = await treasury_agent.run()

    assert run.narration is not None
    assert len(run.narration) > 0


async def test_run_records_are_stored(monkeypatch):
    _patch_settings(monkeypatch)

    await treasury_agent.run()
    await treasury_agent.run()

    runs = treasury_agent.list_runs()
    assert len(runs) == 2
    # Most recent first.
    assert runs[0].started_at >= runs[1].started_at


# ── goal_from_create ──────────────────────────────────────────────────────────

def test_goal_from_create_assigns_id():
    req = TreasuryGoalCreate(
        name="Test",
        beneficiary_name="Vendor",
        beneficiary_address="rVENDOR",
        beneficiary_country="DE",
        amount=500.0,
        currency="EUR",
        reference="REF-001",
        purpose="test",
    )
    goal = treasury_agent.goal_from_create(req)
    assert goal.id  # non-empty UUID
    assert goal.name == "Test"
    assert goal.trigger_interval_hours == 24.0  # default
