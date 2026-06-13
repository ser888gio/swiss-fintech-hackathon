from datetime import datetime, timezone

from app.schemas import (
    ComplianceResult,
    Payment,
    PaymentIntent,
    PaymentStatus,
    PublicIntelResult,
    SanctionsMatch,
)
from app.tools import receipt


def _payment(compliance: ComplianceResult) -> Payment:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return Payment(
        id="pay-001",
        intent=PaymentIntent(**{
            "from": "rSender",
            "to": "rReceiver",
            "senderName": "Alice AG",
            "senderCountry": "CH",
            "receiverName": "Bob Smith",
            "receiverCountry": "GB",
            "receiverEntityType": "individual",
            "purpose": "supplier_payment",
            "amount": 500.0,
            "currency": "USD",
            "reference": "INV-001",
        }),
        compliance=compliance,
        status=PaymentStatus.blocked,
        created_at=now,
        updated_at=now,
    )


def test_receipt_hash_includes_sanctions_and_public_intel_fields():
    clean = ComplianceResult(
        aml_score=10,
        sanctioned=False,
        flags=[],
        explanation="Clean screen.",
        sanctions_matches=[],
        public_intel=PublicIntelResult(
            score=0,
            confidence="not_run",
            flags=[],
            sources=[],
            summary="Public intelligence disabled.",
        ),
    )
    flagged = clean.model_copy(
        update={
            "sanctions_matches": [
                SanctionsMatch(
                    id="NK-123",
                    caption="Blocked Person",
                    schema_="Person",
                    score=0.91,
                    datasets=["us_ofac_sdn"],
                    url="https://www.opensanctions.org/entities/NK-123/",
                )
            ],
            "public_intel": PublicIntelResult(
                score=72,
                confidence="medium",
                flags=["adverse public intelligence signal"],
                sources=["https://example.test/report"],
                summary="Adverse public intelligence signal found.",
            ),
        }
    )

    assert receipt.compute_receipt_hash(_payment(clean)) != receipt.compute_receipt_hash(_payment(flagged))
