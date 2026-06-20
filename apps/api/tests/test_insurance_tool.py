"""Async settlement tool — quote → bind → claim, in mock mode (spec §7/§8)."""

import pytest

from app.schemas import BindRequest, ClaimRequest, InsuranceQuoteRequest, QuoteDecision, TxnContext
from app.tools import insurance as ins


@pytest.fixture(autouse=True)
def _reset_state():
    ins.reset_mock_state()
    yield
    ins.reset_mock_state()


def _txn(amount: str = "5000", lines=("merchant_default",)) -> TxnContext:
    return TxnContext(
        category="supplier_payment",
        tenor_band="lt_30d",
        cpty_band="known",
        first_seen=False,
        amount=amount,
        active_lines=list(lines),
    )


def _quote_req(agent: str = "rA", amount: str = "5000", lines=("merchant_default",)) -> InsuranceQuoteRequest:
    return InsuranceQuoteRequest(agent_address=agent, score_band="STANDARD", txn_context=_txn(amount, lines))


async def test_quote_then_bind_settles_a_premium():
    q = ins.quote(_quote_req())
    assert q.decision is QuoteDecision.offer

    rec = await ins.bind(
        BindRequest(agent_address="rA", job_id="job1", score_band="STANDARD", currency="USD", quote=q)
    )
    assert rec.tx_hash and len(rec.tx_hash) == 64
    assert ins.list_premiums()[0].job_id == "job1"
    assert float(ins.get_pool_status().premiums_collected) > 0


async def test_claim_pays_waterfall_and_reprices_up():
    q = ins.quote(_quote_req(amount="20000"))
    await ins.bind(BindRequest(agent_address="rA", job_id="job1", score_band="STANDARD", currency="USD", quote=q))
    before = ins.get_agent_risk_state("rA").pd

    payout = await ins.settle_claim(ClaimRequest(
        job_id="job1", agent_address="rA", merchant="rM",
        claim_amount="10000", collateral_available="2000",
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
            claim_amount="1000", collateral_available="0",
        ))
    with pytest.raises(ins.PayoutRefused):
        await ins.settle_claim(ClaimRequest(
            job_id="j3", agent_address="rA", merchant="rM",
            claim_amount="1000", collateral_available="0",
        ))


async def test_bind_rejects_a_non_offer_quote():
    # A huge lender-credit exposure breaches pool capacity → REVIEW, not OFFER.
    q = ins.quote(_quote_req(agent="rB", amount="100000000", lines=("lender_credit",)))
    assert q.decision is not QuoteDecision.offer
    with pytest.raises(ins.CoverUnavailable):
        await ins.bind(
            BindRequest(agent_address="rB", job_id="jX", score_band="STANDARD", currency="USD", quote=q)
        )
