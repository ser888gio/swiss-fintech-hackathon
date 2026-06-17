"""Tests for the XLS-33 MPToken compliance-attestation tool.

Covers mock-mode operations only (no network access in CI):
  create_issuance()    — deterministic issuance_id; state updated.
  authorize_holder()   — deduplication; state updated.
  mint_attestation()   — total_minted increments; attestation recorded.
  get_mpt_state()      — returns a snapshot, not a live reference.

Integration: treasury_agent mints after auto-settle when mpt_enabled=True.
"""

from __future__ import annotations

import pytest

from app.tools import mptoken as mpt


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_mpt():
    """Restore in-memory MPT state before each test."""
    mpt._state.update({
        "issuance_id": None,
        "authorized": [],
        "total_minted": 0,
        "attestations": [],
    })
    yield
    mpt._state.update({
        "issuance_id": None,
        "authorized": [],
        "total_minted": 0,
        "attestations": [],
    })


# ── create_issuance ────────────────────────────────────────────────────────────

async def test_create_issuance_returns_issuance_id(monkeypatch):
    monkeypatch.setattr("app.tools.mptoken.get_settings", lambda: _mock_settings())
    result = await mpt.create_issuance()
    assert result.issuance_id  # non-empty
    assert result.tx_hash      # non-empty
    assert result.explorer_url is None   # mock has no URL
    assert result.metadata_hex == mpt.COMPLY_METADATA


async def test_create_issuance_is_deterministic(monkeypatch):
    monkeypatch.setattr("app.tools.mptoken.get_settings", lambda: _mock_settings())
    r1 = await mpt.create_issuance()
    mpt._state["issuance_id"] = None  # reset to re-create
    r2 = await mpt.create_issuance()
    assert r1.issuance_id == r2.issuance_id


async def test_create_issuance_updates_state(monkeypatch):
    monkeypatch.setattr("app.tools.mptoken.get_settings", lambda: _mock_settings())
    result = await mpt.create_issuance()
    assert mpt._state["issuance_id"] == result.issuance_id


# ── authorize_holder ──────────────────────────────────────────────────────────

async def test_authorize_holder_adds_to_list(monkeypatch):
    monkeypatch.setattr("app.tools.mptoken.get_settings", lambda: _mock_settings())
    await mpt.authorize_holder("ISSUANCE_ABC", "rHolder1")
    assert "rHolder1" in mpt._state["authorized"]


async def test_authorize_holder_deduplicates(monkeypatch):
    monkeypatch.setattr("app.tools.mptoken.get_settings", lambda: _mock_settings())
    await mpt.authorize_holder("ISSUANCE_ABC", "rHolder1")
    await mpt.authorize_holder("ISSUANCE_ABC", "rHolder1")
    assert mpt._state["authorized"].count("rHolder1") == 1


async def test_authorize_holder_returns_op_result(monkeypatch):
    monkeypatch.setattr("app.tools.mptoken.get_settings", lambda: _mock_settings())
    result = await mpt.authorize_holder("ISSUANCE_ABC", "rHolder2")
    assert result.operation == "authorize"
    assert result.recipient == "rHolder2"
    assert result.amount == 0
    assert result.tx_hash


# ── mint_attestation ──────────────────────────────────────────────────────────

async def test_mint_increments_total_minted(monkeypatch):
    monkeypatch.setattr("app.tools.mptoken.get_settings", lambda: _mock_settings())
    await mpt.mint_attestation("ISS1", "rRecip", "pay-001", 1000.0)
    await mpt.mint_attestation("ISS1", "rRecip", "pay-002", 2000.0)
    assert mpt._state["total_minted"] == 2


async def test_mint_records_attestation(monkeypatch):
    monkeypatch.setattr("app.tools.mptoken.get_settings", lambda: _mock_settings())
    await mpt.mint_attestation("ISS1", "rRecip", "pay-001", 500.0)
    assert len(mpt._state["attestations"]) == 1
    att = mpt._state["attestations"][0]
    assert att["recipient"] == "rRecip"
    assert att["payment_id"] == "pay-001"
    assert att["amount_settled"] == 500.0
    assert att["tx_hash"]


async def test_mint_returns_amount_1(monkeypatch):
    monkeypatch.setattr("app.tools.mptoken.get_settings", lambda: _mock_settings())
    result = await mpt.mint_attestation("ISS1", "rRecip", "pay-001", 100.0)
    assert result.amount == 1
    assert result.operation == "mint"


async def test_mint_deterministic_hash(monkeypatch):
    monkeypatch.setattr("app.tools.mptoken.get_settings", lambda: _mock_settings())
    r1 = await mpt.mint_attestation("ISS1", "rRecip", "pay-001", 100.0)
    # Reset state so we can re-mint the same payment
    mpt._state["attestations"].clear()
    mpt._state["total_minted"] = 0
    r2 = await mpt.mint_attestation("ISS1", "rRecip", "pay-001", 100.0)
    assert r1.tx_hash == r2.tx_hash


# ── get_mpt_state ─────────────────────────────────────────────────────────────

async def test_get_mpt_state_returns_snapshot(monkeypatch):
    monkeypatch.setattr("app.tools.mptoken.get_settings", lambda: _mock_settings())
    await mpt.mint_attestation("ISS1", "rR", "pay-001", 1.0)
    snap = mpt.get_mpt_state()
    # Mutating the snapshot must not affect internal state
    snap["total_minted"] = 999
    assert mpt._state["total_minted"] == 1


# ── Agent integration ─────────────────────────────────────────────────────────

async def test_agent_mints_after_auto_settle(monkeypatch):
    """When mpt_enabled=True and a payment settles, the agent mints an attestation."""
    from app.agents import treasury_agent
    from tests.test_treasury_agent import _goal, _patch_settings

    treasury_agent._goals.clear()
    treasury_agent._runs.clear()
    treasury_agent.add_goal(_goal(last_triggered_at=None))
    _patch_settings(monkeypatch, mpt_enabled=True, mpt_issuance_id="MOCK_ISS_001")

    run = await treasury_agent.run()

    assert any("[mpt]" in line for line in run.trigger_log)
    assert mpt._state["total_minted"] >= 1

    treasury_agent._goals.clear()
    treasury_agent._runs.clear()


async def test_agent_no_mint_when_disabled(monkeypatch):
    """When mpt_enabled=False the agent does not mint anything."""
    from app.agents import treasury_agent
    from tests.test_treasury_agent import _goal, _patch_settings

    treasury_agent._goals.clear()
    treasury_agent._runs.clear()
    treasury_agent.add_goal(_goal(last_triggered_at=None))
    _patch_settings(monkeypatch, mpt_enabled=False)

    run = await treasury_agent.run()

    assert mpt._state["total_minted"] == 0

    treasury_agent._goals.clear()
    treasury_agent._runs.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_settings(**overrides):
    from types import SimpleNamespace
    data = {
        "use_mock_xrpl": True,
        "treasury_wallet_seed": "",
        "xrpl_endpoint": "wss://s.altnet.rippletest.net:51233",
        "mpt_xrpl_endpoint": "",
        "mpt_recipient_address": "",
        "mpt_recipient_seed": "",
    }
    data.update(overrides)
    return SimpleNamespace(**data)
