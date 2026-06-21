from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas import BindRequest, InsuranceQuoteRequest
from app.tools import insurance as ins


@pytest.fixture(autouse=True)
def reset_insurance_state():
    ins.reset_mock_state()
    yield
    ins.reset_mock_state()


@pytest.mark.anyio
async def test_pricing_is_internal_while_claim_and_pool_remain_public():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/treasury/insurance/quote", json={})).status_code == 404
        assert (await client.post("/treasury/insurance/bind", json={})).status_code == 404

        quote = ins.quote(InsuranceQuoteRequest.model_validate({
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
        }))
        await ins.bind(BindRequest(
            job_id="job-001",
            agent_address="rAGENT",
            score_band="STANDARD",
            currency="USD",
            quote=quote,
        ))

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
