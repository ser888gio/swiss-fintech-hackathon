"""Async settlement tool — quote → bind → claim, in mock mode (spec §7/§8)."""

import pytest

from app.schemas import BindRequest, ClaimRequest, CoverLine, InsuranceQuoteRequest, QuoteDecision
from app.tools import insurance as ins


@pytest.fixture(autouse=True)
def _reset_state():
    ins.reset_mock_state()
    yield
    ins.reset_mock_state()


async def test_quote_then_bind_settles_a_premium():
    q = ins.quote(InsuranceQuoteRequest(agent_address="rA", amount="5000", score_band="STANDARD"))
    assert q.decision is QuoteDecision.OFFER

    rec = await ins.bind(BindRequest(agent_address="rA", job_id="job1", amount="5000", score_band="STANDARD"))
    assert rec.tx_hash and len(rec.tx_hash) == 64
    assert ins.list_premiums()[0].job_id == "job1"
    assert float(ins.get_pool_status().premiums_collected) > 0


async def test_claim_pays_waterfall_and_reprices_up():
    await ins.bind(BindRequest(agent_address="rA", job_id="job1", amount="20000", score_band="STANDARD"))
    before = ins.get_agent_risk_state("rA").pd

    payout = await ins.settle_claim(ClaimRequest(
        job_id="job1", agent_address="rA", merchant="rM",
        line=CoverLine.merchant_default, loss="10000", collateral="2000",
    ))
    assert float(payout.collateral_slashed) == 2000.0
    assert float(payout.pool_drawn) > 0
    assert payout.reputation_mpt_protected is True

    after = ins.get_agent_risk_state("rA").pd
    assert after > before                                   # default repriced the posterior up
    assert float(ins.get_pool_status().payouts_made) > 0    # pool drew down


async def test_collusion_guard_blocks_repeated_pair_payouts():
    for i in range(2):
        await ins.settle_claim(ClaimRequest(
            job_id=f"j{i}", agent_address="rA", merchant="rM",
            line=CoverLine.merchant_default, loss="1000", collateral="0",
        ))
    with pytest.raises(ins.PayoutRefused):
        await ins.settle_claim(ClaimRequest(
            job_id="j3", agent_address="rA", merchant="rM",
            line=CoverLine.merchant_default, loss="1000", collateral="0",
        ))


async def test_bind_rejects_a_non_offer_quote():
    # A huge lender-credit exposure breaches pool capacity → REVIEW, not OFFER.
    with pytest.raises(ins.CoverUnavailable):
        await ins.bind(BindRequest(
            agent_address="rB", job_id="jX", amount="100000000",
            active_lines=[CoverLine.lender_credit], score_band="STANDARD",
        ))
