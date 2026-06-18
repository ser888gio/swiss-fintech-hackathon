"""Tests for the audit-report PDF renderer.

Proves that `build_receipt_pdf` produces a valid, non-empty PDF document from a
terminal payment, and tolerates a sparse payment whose optional sub-objects
(route / compliance / policy) are absent.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.schemas import (
    ComplianceResult,
    Payment,
    PaymentIntent,
    PaymentStatus,
    PolicyDecision,
    PublicIntelResult,
    RouteQuote,
    SanctionsMatch,
)
from app.tools import receipt_pdf


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _full_payment() -> Payment:
    now = _now()
    return Payment(
        id="pay-pdf-001",
        intent=PaymentIntent(**{
            "from": "rSender",
            "to": "rReceiver",
            "senderName": "Alice AG",
            "senderCountry": "CH",
            "receiverName": "Bob LLC",
            "receiverCountry": "US",
            "receiverEntityType": "company",
            "purpose": "supplier_payment",
            "amount": 1000.0,
            "currency": "EUR",
            "reference": "INV-001",
        }),
        route_quote=RouteQuote(
            source_amount=1000.0,
            dest_amount=1090.0,
            rate=1.09,
            path_summary="EUR->USD @ 1.09 (direct)",
            estimated_fee=1.09,
        ),
        compliance=ComplianceResult(
            aml_score=25,
            sanctioned=False,
            flags=["receiver country is high risk (RU)"],
            explanation="Risk score 25/100.",
            sanctions_matches=[
                SanctionsMatch(
                    id="ofac-1",
                    caption="Some Entity",
                    schema="Company",
                    score=0.82,
                    datasets=["us_ofac_sdn"],
                ),
            ],
            public_intel=PublicIntelResult(
                score=10, confidence="high", flags=[], sources=["news"], summary="No adverse media."
            ),
        ),
        policy_decision=PolicyDecision(
            requires_approval=True,
            rule_fired="amount_over_threshold",
            reasons=["amount exceeds 1000 EUR auto-settle cap"],
        ),
        status=PaymentStatus.released,
        approval_signature="ab" * 32,
        tx_hash="A" * 64,
        explorer_url="https://testnet.xrpl.org/transactions/" + "A" * 64,
        receipt_hash="deadbeef" * 8,
        audit_explanation="Escalated for hardware approval, then released.",
        created_at=now,
        updated_at=now,
    )


def _sparse_payment() -> Payment:
    now = _now()
    return Payment(
        id="pay-pdf-002",
        intent=PaymentIntent(**{
            "from": "rSender",
            "to": "rReceiver",
            "senderName": "Alice AG",
            "senderCountry": "CH",
            "receiverName": "Bob LLC",
            "receiverCountry": "US",
            "receiverEntityType": "individual",
            "purpose": "refund",
            "amount": 5.0,
            "currency": "EUR",
            "reference": "REF-2",
        }),
        status=PaymentStatus.blocked,
        created_at=now,
        updated_at=now,
    )


def test_build_receipt_pdf_returns_valid_pdf():
    pdf = receipt_pdf.build_receipt_pdf(_full_payment())
    assert isinstance(pdf, bytes)
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1000


def test_build_receipt_pdf_handles_missing_subobjects():
    pdf = receipt_pdf.build_receipt_pdf(_sparse_payment())
    assert pdf.startswith(b"%PDF-")
