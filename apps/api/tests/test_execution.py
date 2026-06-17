import json

from app.schemas import PaymentIntent, RouteQuote
from app.tools.execution import (
    COMPLIANCE_MEMO_TYPE,
    ComplianceMemo,
    build_memo_fields,
    execute_payment,
    finish_escrow,
    lock_payment,
)


def _intent() -> PaymentIntent:
    return PaymentIntent(**{
        "from": "rSender",
        "to": "rReceiver",
        "senderName": "Alice AG",
        "senderCountry": "CH",
        "receiverName": "Bob LLC",
        "receiverCountry": "US",
        "receiverEntityType": "company",
        "purpose": "supplier_payment",
        "amount": 500.0,
        "currency": "USD",
        "reference": "INV-001",
    })


def _route() -> RouteQuote:
    return RouteQuote(
        source_amount=500.0,
        dest_amount=500.0,
        rate=1.0,
        path_summary="Mock route",
        estimated_fee=0.01,
    )


async def test_mock_direct_payment_does_not_emit_dead_explorer_link():
    result = await execute_payment("pay-test-001", _intent(), _route())

    assert len(result.tx_hash) == 64
    assert result.explorer_url is None


async def test_mock_escrow_paths_do_not_emit_dead_explorer_links():
    escrow = await lock_payment("pay-test-002", _intent(), _route())
    released = await finish_escrow("pay-test-002", escrow.escrow_sequence)

    assert len(escrow.tx_hash) == 64
    assert escrow.explorer_url is None
    assert len(released.tx_hash) == 64
    assert released.explorer_url is None


def test_build_memo_fields_roundtrips_compliance_data():
    memo = ComplianceMemo(aml_score=95, rule_fired="amount_threshold", receipt_hash="deadbeef")
    fields = build_memo_fields(memo)

    assert len(fields) == 1
    field = fields[0]
    # Memo type/data must be uppercase hex.
    assert field["memo_type"] == COMPLIANCE_MEMO_TYPE.encode().hex().upper()
    assert field["memo_data"].isupper() or field["memo_data"].isdigit()

    decoded = json.loads(bytes.fromhex(field["memo_data"]).decode())
    assert decoded == {
        "aml_score": 95,
        "rule_fired": "amount_threshold",
        "receipt_hash": "deadbeef",
    }


def test_build_memo_fields_defaults_missing_rule_to_none_string():
    fields = build_memo_fields(ComplianceMemo(aml_score=10, rule_fired=None, receipt_hash="abc"))
    decoded = json.loads(bytes.fromhex(fields[0]["memo_data"]).decode())
    assert decoded["rule_fired"] == "none"
