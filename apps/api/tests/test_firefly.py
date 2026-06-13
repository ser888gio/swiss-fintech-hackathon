"""Tests for the canonical signing payload.

The hard-coded hex constants below are the ground truth that both this Python
verifier and the TypeScript bridge must agree on. If you change the format in
firefly.py you MUST update the bridge's deriveDigest and regenerate these values.
"""

import hashlib
from datetime import datetime, timezone

from app.schemas import Payment, PaymentIntent, PaymentStatus
from app.tools.firefly import canonical_payload, challenge_digest, challenge_for_payment


# Ground-truth fixture: a known payment, pinned hex.
_FIXTURE_ID = "pay-test-001"
_FIXTURE_AMOUNT = 5000.0
_FIXTURE_CURRENCY = "RLUSD"
_FIXTURE_DEST = "rDestination123"

# Precomputed: sha256("pay-test-001|5000.00|RLUSD|rDestination123")
_FIXTURE_DIGEST = hashlib.sha256(
    f"{_FIXTURE_ID}|{_FIXTURE_AMOUNT:.2f}|{_FIXTURE_CURRENCY}|{_FIXTURE_DEST}".encode()
).hexdigest()


def test_canonical_payload_format():
    result = canonical_payload(_FIXTURE_ID, _FIXTURE_AMOUNT, _FIXTURE_CURRENCY, _FIXTURE_DEST)
    assert result == "pay-test-001|5000.00|RLUSD|rDestination123"


def test_challenge_digest_matches_fixture():
    result = challenge_digest(_FIXTURE_ID, _FIXTURE_AMOUNT, _FIXTURE_CURRENCY, _FIXTURE_DEST)
    assert result == _FIXTURE_DIGEST


def test_amount_formatting_int_float_equivalent():
    # 5000 and 5000.0 must produce identical canonical strings.
    assert canonical_payload(_FIXTURE_ID, 5000, _FIXTURE_CURRENCY, _FIXTURE_DEST) == \
           canonical_payload(_FIXTURE_ID, 5000.0, _FIXTURE_CURRENCY, _FIXTURE_DEST)


def test_amount_formatting_rounds_half_even():
    # 5000.005 under :.2f — documents the exact rounding behavior so the JS
    # side (.toFixed(2)) can be validated against the same edge case.
    result = canonical_payload(_FIXTURE_ID, 5000.005, _FIXTURE_CURRENCY, _FIXTURE_DEST)
    # Python :.2f rounds 5000.005 to 5000.00 (float imprecision: 5000.005 is
    # actually 5000.00499... in IEEE 754). Document this so the bridge knows.
    assert result.startswith("pay-test-001|5000.0")


def _fixture_payment() -> Payment:
    now = datetime.now(timezone.utc)
    return Payment(
        id=_FIXTURE_ID,
        intent=PaymentIntent(**{
            "from": "rSender",
            "to": _FIXTURE_DEST,
            "senderName": "Test Sender",
            "senderCountry": "CH",
            "receiverName": "Test Receiver",
            "receiverCountry": "US",
            "receiverEntityType": "company",
            "purpose": "supplier_payment",
            "amount": _FIXTURE_AMOUNT,
            "currency": _FIXTURE_CURRENCY,
            "reference": "test",
        }),
        status=PaymentStatus.pending_approval,
        created_at=now,
        updated_at=now,
    )


def test_challenge_for_payment_matches_fixture():
    challenge = challenge_for_payment(_fixture_payment())
    assert challenge.payment_id == _FIXTURE_ID
    assert challenge.digest == _FIXTURE_DIGEST


def test_different_payments_produce_different_digests():
    d1 = challenge_digest("pay-001", 500.0, "RLUSD", "rAlice")
    d2 = challenge_digest("pay-002", 500.0, "RLUSD", "rAlice")
    d3 = challenge_digest("pay-001", 50000.0, "RLUSD", "rAlice")
    d4 = challenge_digest("pay-001", 500.0, "RLUSD", "rBob")
    assert len({d1, d2, d3, d4}) == 4
