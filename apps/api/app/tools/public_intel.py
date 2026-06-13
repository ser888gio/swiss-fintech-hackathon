"""Public-intelligence risk scaffold.

Future versions can let AI agents collect and summarize public evidence here,
but the payment outcome must still be computed by deterministic code. This v1
module deliberately does not crawl the web or call search APIs.
"""

from __future__ import annotations

from ..config import get_settings
from ..schemas import PaymentIntent, PublicIntelResult


def assess_public_intel(intent: PaymentIntent) -> PublicIntelResult:
    settings = get_settings()
    if not settings.public_intel_enabled:
        return PublicIntelResult(
            score=0,
            confidence="not_run",
            flags=[],
            sources=[],
            summary="Public intelligence layer disabled; no OSINT risk added.",
        )

    return PublicIntelResult(
        score=0,
        confidence="not_implemented",
        flags=[],
        sources=[],
        summary=(
            "Public intelligence layer is enabled but no evidence agents are "
            f"configured for {intent.receiver_name}."
        ),
    )
