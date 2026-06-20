"""LP capital provision + per-party compliance guardrails (protocol §2, §3)."""

from decimal import Decimal

import pytest

from app.schemas import (
    BindRequest,
    CapitalDepositRequest,
    CapitalWithdrawRequest,
    ClaimRequest,
    CoverLine,
)
from app.tools import insurance as ins

SANCTIONED = "rSANCTIONED000000000000000000000000"  # from compliance.SANCTIONED_ACCOUNTS


@pytest.fixture(autouse=True)
def _reset_state():
    ins.reset_mock_state()
    yield
    ins.reset_mock_state()


async def test_lp_deposit_grows_pool_and_gives_full_share():
    p0 = Decimal(ins.get_pool_status().first_loss)
    pos = await ins.deposit_capital(CapitalDepositRequest(lp_address="rLP1", amount="50000"))
    assert pos.lp_address == "rLP1"
    assert Decimal(pos.capital) == Decimal("50000")
    assert pos.share_pct == 1.0
    status = ins.get_pool_status()
    assert Decimal(status.first_loss) == p0 + Decimal("50000")
    assert Decimal(status.lp_capital) == Decimal("50000")


async def test_two_lps_split_share_pro_rata():
    await ins.deposit_capital(CapitalDepositRequest(lp_address="rLP1", amount="30000"))
    await ins.deposit_capital(CapitalDepositRequest(lp_address="rLP2", amount="10000"))
    by_addr = {p.lp_address: p for p in ins.list_positions()}
    assert abs(by_addr["rLP1"].share_pct - 0.75) < 1e-9
    assert abs(by_addr["rLP2"].share_pct - 0.25) < 1e-9


async def test_lp_withdraw_is_clamped_to_held():
    await ins.deposit_capital(CapitalDepositRequest(lp_address="rLP1", amount="10000"))
    pos = await ins.withdraw_capital(CapitalWithdrawRequest(lp_address="rLP1", amount="999999"))
    assert Decimal(pos.capital) == Decimal("0")
    assert ins.list_positions() == []


async def test_bind_carries_a_passing_guardrail_trail():
    rec = await ins.bind(BindRequest(agent_address="rGOODAGENT", job_id="j1", amount="5000", score_band="STANDARD"))
    names = {g.name for g in rec.guardrail_trail}
    assert {"G1_kya", "G2_sanctions"} <= names
    assert all(g.passed for g in rec.guardrail_trail)


async def test_sanctioned_agent_cannot_bind_cover():
    with pytest.raises(ins.GuardrailRefused):
        await ins.bind(BindRequest(agent_address=SANCTIONED, job_id="j2", amount="5000", score_band="STANDARD"))


async def test_sanctioned_lp_cannot_add_capital():
    with pytest.raises(ins.GuardrailRefused):
        await ins.deposit_capital(CapitalDepositRequest(lp_address=SANCTIONED, amount="1000"))


async def test_payout_trail_includes_party_gate_and_collusion():
    await ins.bind(BindRequest(agent_address="rGOODAGENT", job_id="j1", amount="10000", score_band="STANDARD"))
    payout = await ins.settle_claim(ClaimRequest(
        job_id="j1", agent_address="rGOODAGENT", merchant="rMERCH",
        line=CoverLine.merchant_default, loss="5000", collateral="0",
    ))
    names = {g.name for g in payout.guardrail_trail}
    assert {"G1_kya", "G2_sanctions", "G6_payout", "G2b_collusion"} <= names
