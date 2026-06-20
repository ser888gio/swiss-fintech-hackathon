from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.insurance import store as insurance_store
from app.main import app
from app.tools import vault as vault_tool


def _settings(**overrides):
    data = {
        "insurance_enabled": True,
        "insurance_premium_cap": 5000.0,
        "insurance_lambda_expense": 0.12,
        "insurance_lambda_capital": 0.08,
        "insurance_lambda_risk_max": 0.22,
        "insurance_tau_days": 30.0,
        "policy_threshold_usd": 10000.0,
        "policy_compliance_flag_score": 60,
        "token_currency": "USD",
        "treasury_wallet_address": "rTREASURY",
        "use_mock_xrpl": True,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


@pytest.fixture(autouse=True)
def reset_insurance_state():
    insurance_store._agent_risks.clear()
    insurance_store._premiums.clear()
    insurance_store._payouts.clear()
    vault_tool._state.update(
        {"vault_id": None, "deposited": 0.0, "shares": 0.0, "wallet_balance": 50_000.0, "operations": []}
    )
    yield
    insurance_store._agent_risks.clear()
    insurance_store._premiums.clear()
    insurance_store._payouts.clear()


@pytest.mark.anyio
async def test_quote_bind_claim_and_pool(monkeypatch):
    from app.routes import insurance as route_mod
    from app.insurance import binding as binding_mod
    from app.tools import execution as execution_mod

    settings = _settings()
    monkeypatch.setattr(route_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(binding_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(execution_mod, "get_settings", lambda: settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        quote_res = await client.post(
            "/insurance/quote",
            json={
                "agentAddress": "rAGENT",
                "scoreBand": "STANDARD",
                "txnContext": {
                    "category": "supplier_payment",
                    "tenorBand": "short",
                    "cptyBand": "standard",
                    "firstSeen": False,
                    "amount": "1200.000000",
                    "activeLines": ["merchant_default"],
                },
            },
        )
        assert quote_res.status_code == 200
        quote = quote_res.json()
        assert quote["decision"] == "OFFER"

        bind_res = await client.post(
            "/insurance/bind",
            json={
                "jobId": "job-001",
                "agentAddress": "rAGENT",
                "scoreBand": "STANDARD",
                "currency": "USD",
                "quote": quote,
            },
        )
        assert bind_res.status_code == 201

        claim_res = await client.post(
            "/insurance/claim",
            json={
                "jobId": "job-001",
                "agentAddress": "rAGENT",
                "merchant": "rMERCHANT",
                "merchantName": "Merchant",
                "merchantCountry": "US",
                "scoreBand": "STANDARD",
                "currency": "USD",
                "claimAmount": "1200.000000",
                "collateralAvailable": "200.000000",
            },
        )
        assert claim_res.status_code == 201
        assert claim_res.json()["poolDrawn"] == "500"

        pool_res = await client.get("/insurance/pool")
        assert pool_res.status_code == 200
        assert pool_res.json()["currency"] == "USD"

        risk_res = await client.get("/insurance/agents/rAGENT/risk")
        assert risk_res.status_code == 200
        assert risk_res.json()["pd"] > 0

