"""Orchestrator cover-requirement gate (spec §3) — auto-bind + regression guard."""

import pytest

from app.agents import orchestrator
from app.schemas import PaymentIntent
from app.tools import insurance as ins


@pytest.fixture(autouse=True)
def _reset_state():
    ins.reset_mock_state()
    yield
    ins.reset_mock_state()


def _intent(**overrides) -> PaymentIntent:
    data = {
        "from_account": "rAgent",
        "to": "rDest",
        "sender_name": "Alice AG",
        "sender_country": "CH",
        "receiver_name": "Bob Ltd",
        "receiver_country": "GB",
        "receiver_entity_type": "company",
        "purpose": "merchant_payment",
        "amount": 500.0,
        "currency": "USD",
        "reference": "INV-001",
    }
    data.update(overrides)
    return PaymentIntent(**data)


async def test_no_cover_required_leaves_flow_unchanged():
    payment = await orchestrator.process_payment(_intent())
    assert payment.status.value == "settled"
    assert ins.list_premiums() == []          # no premium bound when cover not required


async def test_cover_required_auto_binds_a_premium_before_settle():
    payment = await orchestrator.process_payment(_intent(cover_required=True))
    premiums = ins.list_premiums()
    assert premiums, "a premium should be auto-bound when cover is required"
    assert premiums[0].job_id == payment.id
    assert payment.status.value == "settled"


async def test_conditional_cover_below_threshold_does_not_bind():
    # Required only above $10k; a $500 payment stays uncovered.
    payment = await orchestrator.process_payment(
        _intent(cover_required=True, cover_required_above_usd=10_000.0)
    )
    assert ins.list_premiums() == []
    assert payment.status.value == "settled"
