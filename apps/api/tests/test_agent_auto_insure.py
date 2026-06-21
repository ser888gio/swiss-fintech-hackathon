from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.routes import agents
from app.schemas import TreasuryAgentRun


@pytest.fixture(autouse=True)
def reset_agents():
    agents._agents.clear()
    yield
    agents._agents.clear()


@pytest.mark.anyio
async def test_agent_auto_insure_create_update_and_run_wiring(monkeypatch):
    payload = {
        "id": "supplier-bot",
        "name": "Supplier Bot",
        "maxSinglePayment": "5000",
        "maxDailySpend": "10000",
        "requiresApprovalAbove": "250",
        "autoInsure": {
            "mode": "on",
            "amountThresholdUsd": 750,
            "insureNewCounterparty": True,
            "insureUnverifiedCounterparty": False,
            "package": "Standard",
        },
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/agents", json=payload)
        assert created.status_code == 201
        assert created.json()["autoInsure"]["package"] == "Standard"

        updated = await client.put("/agents/supplier-bot", json={"autoInsure": {"mode": "off"}})
        assert updated.status_code == 200
        assert updated.json()["autoInsure"]["mode"] == "off"

        captured = {}

        async def fake_run(agent_id, agent_scope, agent_cover):
            captured["cover"] = agent_cover
            now = datetime.now(timezone.utc)
            return TreasuryAgentRun(
                id="run-1", started_at=now, completed_at=now,
                goals_evaluated=0, goals_triggered=0,
                payments_initiated=[], payments_skipped=[], trigger_log=[],
                narration=None, status="completed", agent_id=agent_id,
            )

        monkeypatch.setattr(agents.treasury_agent, "run_for_agent", fake_run)
        run = await client.post("/agents/supplier-bot/run")
        assert run.status_code == 200
        assert captured["cover"].mode == "off"


def test_agent_row_hydrates_auto_insure_override():
    now = datetime.now(timezone.utc)
    row = SimpleNamespace(
        id="agent", name="Agent", description=None, status="active", currency="RLUSD",
        max_single_payment="50", max_daily_spend="200", requires_approval_above="25",
        allowed_categories=None, allowed_assets=["RLUSD"], allowed_network="xrpl:1",
        allowed_addresses=None, blocked_addresses=[], allowed_hosts=None, blocked_hosts=[],
        require_known_merchant=False, policy_revision=1, created_at=now, updated_at=now,
        auto_insure={"mode": "on", "amount_threshold_usd": 500, "package": "Essential"},
    )
    agent = agents._row_to_agent(row)
    assert agent.auto_insure is not None
    assert agent.auto_insure.amount_threshold_usd == 500
