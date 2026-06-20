from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.tools import insurance as ins


@pytest.fixture(autouse=True)
def reset_insurance_state():
    ins.reset_mock_state()
    yield
    ins.reset_mock_state()


@pytest.mark.anyio
async def test_quote_bind_claim_and_pool():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        quote_res = await client.post(
            "/treasury/insurance/quote",
            json={
                "agentAddress": "rAGENT",
                "scoreBand": "STANDARD",
                "txnContext": {
                    "category": "supplier_payment",
                    "tenorBand": "lt_30d",
                    "cptyBand": "known",
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
            "/treasury/insurance/bind",
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
            "/treasury/insurance/claim",
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
        # collateral covers 200; the pool draws the recovery_rate-bounded residual.
        assert claim_res.json()["poolDrawn"] == "900.00"

        pool_res = await client.get("/treasury/insurance/pool")
        assert pool_res.status_code == 200
        assert pool_res.json()["currency"]

        risk_res = await client.get("/treasury/insurance/agents/rAGENT/risk")
        assert risk_res.status_code == 200
        assert risk_res.json()["pd"] > 0
