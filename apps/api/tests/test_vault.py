"""Tests for the XLS-65 vault tool and treasury agent vault sweep.

All tests run in mock mode (use_mock_xrpl=True) so they never touch the
network. The vault state is reset before each test via the reset_vault fixture.
"""

from __future__ import annotations

import pytest
from unittest.mock import patch

from app.tools import vault as vault_mod
from app.config import Settings


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_vault():
    """Reset in-memory vault state before each test."""
    vault_mod._state.update({
        "vault_id": None,
        "deposited": 0.0,
        "shares": 0.0,
        "wallet_balance": 50_000.0,
        "operations": [],
    })
    yield


def mock_settings(**overrides) -> Settings:
    base = {
        "use_mock_xrpl": True,
        "token_currency": "USD",
        "token_issuer_address": "rISSUER",
        "vault_enabled": True,
        "vault_xrpl_endpoint": "wss://s.devnet.rippletest.net:51233",
        "vault_sweep_threshold_usd": 5_000.0,
        "vault_recall_threshold_usd": 1_000.0,
        "vault_id": "",
        "treasury_wallet_seed": "",
        "database_url": "sqlite+aiosqlite:///:memory:",
        "openai_api_key": "",
        "openai_model": "gpt-4o",
    }
    base.update(overrides)
    return Settings(**base)


# ── vault_create ──────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_create_vault_mock_returns_vault_id():
    with patch("app.tools.vault.get_settings", return_value=mock_settings()):
        result = await vault_mod.create_vault("USD", "rISSUER")

    assert result.vault_id
    assert len(result.tx_hash) == 64  # sha256 hex
    assert result.explorer_url is None  # mock: no real URL
    assert vault_mod._state["vault_id"] == result.vault_id


@pytest.mark.anyio
async def test_create_vault_records_operation():
    with patch("app.tools.vault.get_settings", return_value=mock_settings()):
        await vault_mod.create_vault("USD", "rISSUER")

    ops = vault_mod._state["operations"]
    assert len(ops) == 1
    assert ops[0]["operation"] == "create"
    assert ops[0]["amount"] == 0.0


@pytest.mark.anyio
async def test_create_vault_id_is_deterministic():
    s = mock_settings()
    with patch("app.tools.vault.get_settings", return_value=s):
        r1 = await vault_mod.create_vault("USD", "rISSUER")
    vault_mod._state.update({"vault_id": None, "operations": []})
    with patch("app.tools.vault.get_settings", return_value=s):
        r2 = await vault_mod.create_vault("USD", "rISSUER")

    assert r1.vault_id == r2.vault_id


# ── vault_deposit ─────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_deposit_updates_state():
    s = mock_settings()
    with patch("app.tools.vault.get_settings", return_value=s):
        await vault_mod.create_vault("USD", "rISSUER")
        result = await vault_mod.deposit(vault_mod._state["vault_id"], 10_000.0)

    assert result.amount == 10_000.0
    assert result.shares_delta == pytest.approx(100.0)  # 10_000 / 100
    assert vault_mod._state["deposited"] == pytest.approx(10_000.0)
    assert vault_mod._state["wallet_balance"] == pytest.approx(40_000.0)
    assert len(vault_mod._state["operations"]) == 2  # create + deposit


@pytest.mark.anyio
async def test_deposit_clamps_to_wallet_balance():
    s = mock_settings()
    vault_mod._state["wallet_balance"] = 3_000.0
    vault_mod._state["vault_id"] = "MOCK_VAULT"
    with patch("app.tools.vault.get_settings", return_value=s):
        result = await vault_mod.deposit("MOCK_VAULT", 5_000.0)

    assert result.amount == pytest.approx(3_000.0)
    assert vault_mod._state["wallet_balance"] == pytest.approx(0.0)


# ── vault_withdraw ────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_withdraw_updates_state():
    s = mock_settings()
    vault_mod._state.update({"vault_id": "V1", "deposited": 20_000.0, "shares": 200.0, "wallet_balance": 30_000.0})
    with patch("app.tools.vault.get_settings", return_value=s):
        result = await vault_mod.withdraw("V1", 5_000.0)

    assert result.amount == pytest.approx(5_000.0)
    assert result.shares_delta == pytest.approx(-50.0)
    assert vault_mod._state["deposited"] == pytest.approx(15_000.0)
    assert vault_mod._state["wallet_balance"] == pytest.approx(35_000.0)


@pytest.mark.anyio
async def test_withdraw_clamps_to_deposited():
    s = mock_settings()
    vault_mod._state.update({"vault_id": "V1", "deposited": 2_000.0, "shares": 20.0})
    with patch("app.tools.vault.get_settings", return_value=s):
        result = await vault_mod.withdraw("V1", 10_000.0)

    assert result.amount == pytest.approx(2_000.0)
    assert vault_mod._state["deposited"] == pytest.approx(0.0)


@pytest.mark.anyio
async def test_withdraw_empty_vault_returns_zero():
    s = mock_settings()
    vault_mod._state["vault_id"] = "V1"
    with patch("app.tools.vault.get_settings", return_value=s):
        result = await vault_mod.withdraw("V1", 1_000.0)

    assert result.amount == pytest.approx(0.0)
    assert vault_mod._state["wallet_balance"] == pytest.approx(50_000.0)


# ── vault sweep in treasury agent ─────────────────────────────────────────────

@pytest.mark.anyio
async def test_sweep_deposits_excess_above_threshold():
    """Wallet balance 50k > threshold 5k → deposits 45k into vault."""
    from app.agents import treasury_agent

    s = mock_settings(vault_enabled=True, vault_sweep_threshold_usd=5_000.0)
    vault_mod._state["wallet_balance"] = 50_000.0
    log: list[str] = []
    with patch("app.agents.treasury_agent.get_settings", return_value=s), \
         patch("app.tools.vault.get_settings", return_value=s):
        await treasury_agent._vault_sweep(log, s)

    assert vault_mod._state["deposited"] == pytest.approx(45_000.0)
    assert vault_mod._state["wallet_balance"] == pytest.approx(5_000.0)
    assert any("Swept" in line for line in log)


@pytest.mark.anyio
async def test_sweep_recalls_when_balance_below_recall_threshold():
    """Wallet balance 500 < recall threshold 1000 → withdraws from vault."""
    from app.agents import treasury_agent

    s = mock_settings(
        vault_enabled=True,
        vault_sweep_threshold_usd=5_000.0,
        vault_recall_threshold_usd=1_000.0,
    )
    vault_mod._state.update({
        "vault_id": "V1",
        "wallet_balance": 500.0,
        "deposited": 20_000.0,
        "shares": 200.0,
    })
    log: list[str] = []
    with patch("app.agents.treasury_agent.get_settings", return_value=s), \
         patch("app.tools.vault.get_settings", return_value=s):
        await treasury_agent._vault_sweep(log, s)

    assert vault_mod._state["wallet_balance"] > 500.0
    assert any("Recalled" in line for line in log)


@pytest.mark.anyio
async def test_sweep_noop_when_balance_in_range():
    """Wallet balance 3000, recall=1000, sweep=5000 → no operation needed."""
    from app.agents import treasury_agent

    s = mock_settings(
        vault_enabled=True,
        vault_sweep_threshold_usd=5_000.0,
        vault_recall_threshold_usd=1_000.0,
    )
    vault_mod._state["wallet_balance"] = 3_000.0
    vault_mod._state["vault_id"] = "V1"
    log: list[str] = []
    with patch("app.agents.treasury_agent.get_settings", return_value=s), \
         patch("app.tools.vault.get_settings", return_value=s):
        await treasury_agent._vault_sweep(log, s)

    assert vault_mod._state["deposited"] == pytest.approx(0.0)
    assert any("no sweep needed" in line for line in log)


@pytest.mark.anyio
async def test_sweep_disabled_when_vault_disabled():
    """vault_enabled=False → _vault_sweep is a no-op."""
    from app.agents import treasury_agent

    s = mock_settings(vault_enabled=False)
    vault_mod._state["wallet_balance"] = 50_000.0
    log: list[str] = []
    with patch("app.agents.treasury_agent.get_settings", return_value=s), \
         patch("app.tools.vault.get_settings", return_value=s):
        await treasury_agent._vault_sweep(log, s)

    assert vault_mod._state["deposited"] == pytest.approx(0.0)
    assert log == []


# ── get_vault_state ───────────────────────────────────────────────────────────

def test_get_vault_state_returns_snapshot():
    vault_mod._state["deposited"] = 12_345.0
    state = vault_mod.get_vault_state()
    assert state["deposited"] == pytest.approx(12_345.0)
    state["deposited"] = 0.0  # mutating snapshot should not affect _state
    assert vault_mod._state["deposited"] == pytest.approx(12_345.0)
