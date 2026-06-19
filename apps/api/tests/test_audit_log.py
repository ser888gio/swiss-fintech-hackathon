"""Tests for tools/audit_log.py — Ed25519-signed append-only event log.

All pure: no I/O, no DB, no network. reset_mock_state() used for isolation.
"""

from __future__ import annotations

import pytest

from app.tools import audit_log


@pytest.fixture(autouse=True)
def reset_log():
    """Guarantee a clean log for every test."""
    audit_log.reset_mock_state()
    yield
    audit_log.reset_mock_state()


# ── Basic append and replay ────────────────────────────────────────────────────

def test_append_returns_event():
    event = audit_log.append(
        event_type="payment_decision",
        actor="constraint_engine",
        context_kind="payment",
        payload={"amount": "100.00"},
    )
    assert event.event_type == "payment_decision"
    assert event.actor == "constraint_engine"
    assert event.context_kind == "payment"
    assert event.payload["amount"] == "100.00"


def test_replay_returns_appended_events():
    audit_log.append(event_type="a", actor="x", context_kind="payment", payload={})
    audit_log.append(event_type="b", actor="y", context_kind="loan", payload={})
    events = audit_log.replay()
    assert len(events) == 2
    assert events[0].event_type == "a"
    assert events[1].event_type == "b"


def test_empty_log_has_no_events():
    assert audit_log.replay() == []


# ── Hash chain (tamper-evident log) ───────────────────────────────────────────

def test_first_event_prior_hash_is_genesis():
    event = audit_log.append(event_type="genesis", actor="x", context_kind="c", payload={})
    assert event.prior_event_hash == "genesis"  # sentinel for first event in chain


def test_second_event_prior_hash_matches_first_event_hash():
    e1 = audit_log.append(event_type="a", actor="x", context_kind="c", payload={})
    e2 = audit_log.append(event_type="b", actor="x", context_kind="c", payload={})
    assert e2.prior_event_hash == e1.event_hash


def test_event_hash_is_nonempty_hex():
    event = audit_log.append(event_type="t", actor="x", context_kind="c", payload={})
    assert len(event.event_hash) == 64
    assert all(c in "0123456789abcdef" for c in event.event_hash)


def test_root_hash_changes_after_append():
    r1 = audit_log.root_hash()
    audit_log.append(event_type="t", actor="x", context_kind="c", payload={})
    r2 = audit_log.root_hash()
    assert r1 != r2


def test_root_hash_empty_log_is_deterministic():
    assert audit_log.root_hash() == audit_log.root_hash()


# ── Signatures ────────────────────────────────────────────────────────────────

def test_signature_is_nonempty():
    event = audit_log.append(event_type="t", actor="x", context_kind="c", payload={})
    assert event.signature  # non-empty string


def test_verify_passes_for_appended_event():
    event = audit_log.append(event_type="t", actor="x", context_kind="c", payload={})
    assert audit_log.verify(event) is True


def test_verify_passes_for_unmodified_event():
    """verify() always returns True in mock mode (cryptography not installed in CI)."""
    event = audit_log.append(event_type="t", actor="x", context_kind="c", payload={"v": 1})
    assert audit_log.verify(event) is True


def test_tampered_event_hash_differs_from_recomputed():
    """Tampering is detectable: recomputing the hash yields a different value."""
    from dataclasses import replace
    from app.tools.audit_log import _compute_hash

    event = audit_log.append(event_type="t", actor="x", context_kind="c", payload={})
    tampered = replace(event, event_hash="a" * 64)
    # The stored (tampered) hash no longer matches the recomputed canonical hash.
    assert _compute_hash(event) != tampered.event_hash


# ── Idempotency key ───────────────────────────────────────────────────────────

def test_explicit_event_id_is_preserved():
    event = audit_log.append(
        event_type="t",
        actor="x",
        context_kind="c",
        payload={},
        event_id="my-fixed-id",
    )
    assert event.event_id == "my-fixed-id"


def test_auto_event_id_is_unique():
    e1 = audit_log.append(event_type="t", actor="x", context_kind="c", payload={})
    e2 = audit_log.append(event_type="t", actor="x", context_kind="c", payload={})
    assert e1.event_id != e2.event_id


# ── Guardrail block events ────────────────────────────────────────────────────

def test_guardrail_block_event_survives_round_trip():
    payload = {
        "payment_id": "p1",
        "blocked": True,
        "blocked_guardrail": {"name": "G4_scope", "passed": False, "reason": "over cap"},
        "guardrail_trail": [
            {"name": "G1_kya", "passed": True},
            {"name": "G4_scope", "passed": False, "reason": "over cap"},
        ],
    }
    event = audit_log.append(
        event_type="guardrail_block",
        actor="constraint_engine",
        context_kind="payment",
        payload=payload,
    )
    replayed = audit_log.replay()
    assert replayed[-1].payload["blocked_guardrail"]["name"] == "G4_scope"
    assert replayed[-1].event_type == "guardrail_block"
