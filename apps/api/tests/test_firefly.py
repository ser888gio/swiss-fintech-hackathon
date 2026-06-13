"""Tests for the canonical signing payload.

The hard-coded hex constants below are the ground truth that both this Python
verifier and the TypeScript bridge must agree on. If you change the format in
firefly.py you MUST update the bridge's deriveDigest and regenerate these values.
"""

import hashlib
from datetime import datetime, timezone

import pytest
from eth_keys import keys

from app.schemas import Payment, PaymentIntent, PaymentStatus
from app.tools.firefly import (
    PAYLOAD_VERSION,
    canonical_payload,
    challenge_digest,
    challenge_for_payment,
    verify_signature,
)

# Ground-truth fixture: a known payment, pinned hex.
_FIXTURE_ID = "pay-test-001"
_FIXTURE_AMOUNT = 5000.0
_FIXTURE_CURRENCY = "RLUSD"
_FIXTURE_DEST = "rDestination123"
_FIXTURE_NETWORK = "xrpl:testnet"
_FIXTURE_OWNER = "r_TREASURY_MOCK"
_FIXTURE_ESCROW_SEQ = 42
_FIXTURE_ESCROW_TX = "ABCDEF1234567890" * 4  # 64-char mock hash

# Precomputed: sha256 of the canonical payload with all fields.
_FIXTURE_CANONICAL = (
    f"{PAYLOAD_VERSION}|{_FIXTURE_NETWORK}|{_FIXTURE_ID}|{_FIXTURE_OWNER}"
    f"|{_FIXTURE_DEST}|{_FIXTURE_CURRENCY}|{_FIXTURE_AMOUNT:.2f}"
    f"|{_FIXTURE_ESCROW_SEQ}|{_FIXTURE_ESCROW_TX}"
)
_FIXTURE_DIGEST = hashlib.sha256(_FIXTURE_CANONICAL.encode()).hexdigest()


def test_canonical_payload_format():
    result = canonical_payload(
        _FIXTURE_ID, _FIXTURE_AMOUNT, _FIXTURE_CURRENCY, _FIXTURE_DEST,
        _FIXTURE_NETWORK, _FIXTURE_OWNER, _FIXTURE_ESCROW_SEQ, _FIXTURE_ESCROW_TX,
    )
    assert result == _FIXTURE_CANONICAL


def test_challenge_digest_matches_fixture():
    result = challenge_digest(
        _FIXTURE_ID, _FIXTURE_AMOUNT, _FIXTURE_CURRENCY, _FIXTURE_DEST,
        _FIXTURE_NETWORK, _FIXTURE_OWNER, _FIXTURE_ESCROW_SEQ, _FIXTURE_ESCROW_TX,
    )
    assert result == _FIXTURE_DIGEST


def test_amount_formatting_int_float_equivalent():
    p1 = canonical_payload(_FIXTURE_ID, 5000, _FIXTURE_CURRENCY, _FIXTURE_DEST,
                           _FIXTURE_NETWORK, _FIXTURE_OWNER, _FIXTURE_ESCROW_SEQ, _FIXTURE_ESCROW_TX)
    p2 = canonical_payload(_FIXTURE_ID, 5000.0, _FIXTURE_CURRENCY, _FIXTURE_DEST,
                           _FIXTURE_NETWORK, _FIXTURE_OWNER, _FIXTURE_ESCROW_SEQ, _FIXTURE_ESCROW_TX)
    assert p1 == p2


def test_amount_formatting_rounds_half_even():
    result = canonical_payload(_FIXTURE_ID, 5000.005, _FIXTURE_CURRENCY, _FIXTURE_DEST,
                               _FIXTURE_NETWORK, _FIXTURE_OWNER, _FIXTURE_ESCROW_SEQ, _FIXTURE_ESCROW_TX)
    # Python :.2f rounds 5000.005 to 5000.00 (IEEE 754 float imprecision).
    assert "|5000.0" in result


def test_different_payments_produce_different_digests():
    def _d(pid, amt, seq, txhash):
        return challenge_digest(pid, amt, _FIXTURE_CURRENCY, _FIXTURE_DEST,
                                _FIXTURE_NETWORK, _FIXTURE_OWNER, seq, txhash)

    d1 = _d("pay-001", 500.0, 1, "aaa")
    d2 = _d("pay-002", 500.0, 1, "aaa")   # different payment_id
    d3 = _d("pay-001", 50000.0, 1, "aaa") # different amount
    d4 = _d("pay-001", 500.0, 2, "aaa")   # different escrow_sequence
    d5 = _d("pay-001", 500.0, 1, "bbb")   # different escrow_create_tx_hash
    assert len({d1, d2, d3, d4, d5}) == 5


def test_network_prefix_differentiates_mainnet_testnet():
    testnet = challenge_digest(
        _FIXTURE_ID, _FIXTURE_AMOUNT, _FIXTURE_CURRENCY, _FIXTURE_DEST,
        "xrpl:testnet", _FIXTURE_OWNER, _FIXTURE_ESCROW_SEQ, _FIXTURE_ESCROW_TX,
    )
    mainnet = challenge_digest(
        _FIXTURE_ID, _FIXTURE_AMOUNT, _FIXTURE_CURRENCY, _FIXTURE_DEST,
        "xrpl:mainnet", _FIXTURE_OWNER, _FIXTURE_ESCROW_SEQ, _FIXTURE_ESCROW_TX,
    )
    assert testnet != mainnet


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
        escrow_sequence=_FIXTURE_ESCROW_SEQ,
        escrow_create_tx_hash=_FIXTURE_ESCROW_TX,
        created_at=now,
        updated_at=now,
    )


def test_challenge_for_payment_matches_fixture(monkeypatch):
    from app import config
    settings = config.get_settings()
    monkeypatch.setattr(settings, "xrpl_network", _FIXTURE_NETWORK)
    monkeypatch.setattr(settings, "treasury_wallet_address", "")  # triggers mock fallback
    challenge = challenge_for_payment(_fixture_payment())
    assert challenge.payment_id == _FIXTURE_ID
    assert challenge.digest == _FIXTURE_DIGEST
    assert challenge.network == _FIXTURE_NETWORK
    assert challenge.owner == _FIXTURE_OWNER


def test_challenge_for_payment_raises_without_escrow_fields():
    now = datetime.now(timezone.utc)
    payment = Payment(
        id="pay-no-escrow",
        intent=PaymentIntent(**{
            "from": "rSender",
            "to": "rDest",
            "senderName": "A",
            "senderCountry": "CH",
            "receiverName": "B",
            "receiverCountry": "US",
            "receiverEntityType": "company",
            "purpose": "test",
            "amount": 100.0,
            "currency": "RLUSD",
            "reference": "ref",
        }),
        status=PaymentStatus.routing,
        created_at=now,
        updated_at=now,
    )
    with pytest.raises(ValueError):
        challenge_for_payment(payment)


# ── verify_signature round-trip tests ─────────────────────────────────────────

_TEST_PRIVKEY = keys.PrivateKey(hashlib.sha256(b"test-firefly-privkey").digest())
_TEST_PUBKEY_HEX = _TEST_PRIVKEY.public_key.to_bytes().hex()


def _sign(digest_hex: str, privkey=_TEST_PRIVKEY) -> str:
    return privkey.sign_msg_hash(bytes.fromhex(digest_hex)).to_bytes().hex()


def test_verify_signature_valid(monkeypatch):
    from app import config
    monkeypatch.setattr(config.get_settings(), "firefly_public_key", _TEST_PUBKEY_HEX)
    assert verify_signature(_FIXTURE_DIGEST, _sign(_FIXTURE_DIGEST)) is True


def test_verify_signature_rejects_wrong_key(monkeypatch):
    from app import config
    wrong_privkey = keys.PrivateKey(hashlib.sha256(b"wrong-key").digest())
    wrong_pubkey = wrong_privkey.public_key.to_bytes().hex()
    monkeypatch.setattr(config.get_settings(), "firefly_public_key", wrong_pubkey)
    assert verify_signature(_FIXTURE_DIGEST, _sign(_FIXTURE_DIGEST)) is False


def test_verify_signature_normalizes_recovery_bytes(monkeypatch):
    """Device may send recovery byte 27 or 28; must be normalized to 0/1."""
    from app import config
    monkeypatch.setattr(config.get_settings(), "firefly_public_key", _TEST_PUBKEY_HEX)
    sig_bytes = bytes.fromhex(_sign(_FIXTURE_DIGEST))
    unnormalized = sig_bytes[:64] + bytes([sig_bytes[64] + 27])
    assert verify_signature(_FIXTURE_DIGEST, unnormalized.hex()) is True


def test_verify_signature_rejects_tampered_digest(monkeypatch):
    from app import config
    monkeypatch.setattr(config.get_settings(), "firefly_public_key", _TEST_PUBKEY_HEX)
    tampered_digest = "ff" + _FIXTURE_DIGEST[2:]
    assert verify_signature(tampered_digest, _sign(_FIXTURE_DIGEST)) is False


def test_verify_signature_no_public_key_configured(monkeypatch):
    from app import config
    monkeypatch.setattr(config.get_settings(), "firefly_public_key", "")
    assert verify_signature(_FIXTURE_DIGEST, _sign(_FIXTURE_DIGEST)) is False


def test_verify_signature_rejects_invalid_hex(monkeypatch):
    from app import config
    monkeypatch.setattr(config.get_settings(), "firefly_public_key", _TEST_PUBKEY_HEX)
    assert verify_signature("not-hex", _sign(_FIXTURE_DIGEST)) is False
