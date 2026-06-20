"""Tests for cover/reconcile.py — pure deterministic claim trigger."""

from decimal import Decimal

import pytest

from app.cover.reconcile import CoverEvent, non_delivery_event, reconcile
from app.schemas import CoverLineKind, CoverLossBearerKind


def test_underpayment_detected():
    event = reconcile(
        expected_amount=500.0,
        executed_amount=480.0,
        expected_recipient="rMERCHANT",
        executed_recipient="rMERCHANT",
    )
    assert event is not None
    assert event.line == CoverLineKind.hallucination
    assert event.classification == "underpayment"
    assert event.loss == Decimal("20.000000")
    assert event.loss_bearer == CoverLossBearerKind.merchant


def test_wrong_recipient_detected():
    event = reconcile(
        expected_amount=500.0,
        executed_amount=500.0,
        expected_recipient="rMERCHANT_A",
        executed_recipient="rMERCHANT_B",
    )
    assert event is not None
    assert event.classification == "wrong_recipient"
    assert event.loss_bearer == CoverLossBearerKind.treasury
    assert event.loss == Decimal("500.000000")


def test_wrong_recipient_takes_priority_over_underpayment():
    # Both conditions present — wrong recipient wins
    event = reconcile(
        expected_amount=500.0,
        executed_amount=480.0,
        expected_recipient="rMERCHANT_A",
        executed_recipient="rMERCHANT_B",
    )
    assert event is not None
    assert event.classification == "wrong_recipient"


def test_no_divergence_returns_none():
    event = reconcile(
        expected_amount=500.0,
        executed_amount=500.0,
        expected_recipient="rMERCHANT",
        executed_recipient="rMERCHANT",
    )
    assert event is None


def test_overpayment_not_covered():
    # Agent paid MORE than expected — not a covered event
    event = reconcile(
        expected_amount=480.0,
        executed_amount=500.0,
        expected_recipient="rMERCHANT",
        executed_recipient="rMERCHANT",
    )
    assert event is None


def test_rounding_tolerance_not_covered():
    # 0.2% rounding — below the 0.5% tolerance
    event = reconcile(
        expected_amount=500.0,
        executed_amount=499.0,
        expected_recipient="rMERCHANT",
        executed_recipient="rMERCHANT",
    )
    assert event is None


def test_no_expected_amount_no_event():
    event = reconcile(
        expected_amount=None,
        executed_amount=480.0,
        expected_recipient=None,
        executed_recipient="rMERCHANT",
    )
    assert event is None


def test_non_delivery_event():
    event = non_delivery_event(300.0)
    assert event.line == CoverLineKind.non_delivery
    assert event.classification == "non_delivery"
    assert event.loss_bearer == CoverLossBearerKind.treasury
    assert event.loss == Decimal("300.000000")
