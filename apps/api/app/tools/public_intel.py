"""Public-intelligence risk scaffold.

Derives behavioural AML signals from the payment history already held in the
in-memory store. No external API calls; all signals are computed from data the
system already owns.

Two signal categories:
  - New counterparty: first time we have seen this receiver — heightened scrutiny.
  - Amount anomaly: this payment is significantly above the historical average
    to the same receiver — possible account-takeover or fraud escalation.

The score produced here is advisory: it can only *raise* the AML score computed
by the compliance tool, never lower it. The compliance tool calls
`max(aml_score, public_intel.score)` after evaluating the deterministic signals.

Future versions can augment this with real OSINT agents (news crawl, corporate
registry lookups), but the policy outcome must always be computed by code — never
by the LLM.
"""

from __future__ import annotations

import statistics

from ..config import get_settings
from ..schemas import PaymentIntent, PaymentStatus, PublicIntelResult


def assess_public_intel(intent: PaymentIntent) -> PublicIntelResult:
    settings = get_settings()
    if not settings.public_intel_enabled:
        return PublicIntelResult(
            score=0,
            confidence="not_run",
            flags=[],
            sources=[],
            summary="Public intelligence layer disabled; no behavioural risk added.",
        )

    flags: list[str] = []
    sources: list[str] = ["payment_history"]
    evidence_parts: list[str] = []

    history = _payment_history(intent.to)

    # ── Signal 1: New counterparty ────────────────────────────────────────────
    is_new = len(history) == 0
    if is_new:
        flags.append(f"first payment to {intent.receiver_name} — no prior history")
        evidence_parts.append(
            f"No prior settled or released payments found for receiver {intent.to}. "
            "New counterparties warrant additional scrutiny."
        )

    # ── Signal 2: Amount anomaly ──────────────────────────────────────────────
    if len(history) >= 2:
        amounts = [p.intent.amount for p in history]
        mean = statistics.mean(amounts)
        stdev = statistics.stdev(amounts) if len(amounts) > 1 else 0.0
        # Flag if current amount is more than 2 standard deviations above mean
        # or more than 3× the historical average (handles low-variance history).
        threshold_stdev = mean + 2 * stdev if stdev > 0 else float("inf")
        threshold_ratio = mean * 3.0
        if intent.amount > max(threshold_stdev, threshold_ratio):
            ratio = intent.amount / mean
            flags.append(
                f"amount {intent.amount:,.2f} {intent.currency} is {ratio:.1f}× the "
                f"historical average to this receiver ({mean:,.2f}) — anomaly"
            )
            evidence_parts.append(
                f"Historical mean to {intent.receiver_name}: {mean:,.2f} "
                f"(n={len(amounts)}, σ={stdev:,.2f}). "
                f"Current amount is {ratio:.1f}× above baseline."
            )

    # ── Score ─────────────────────────────────────────────────────────────────
    score = _compute_score(is_new, len(flags))
    confidence = "medium" if len(history) >= 3 else "low"
    summary = " ".join(evidence_parts) if evidence_parts else ""

    return PublicIntelResult(
        score=score,
        confidence=confidence,
        flags=flags,
        sources=sources,
        summary=summary,
    )


def _payment_history(receiver_address: str):
    """Return settled or released payments to this receiver from the store.

    Silently returns an empty list if the store is unavailable (test context).
    """
    try:
        from .. import store

        terminal = {PaymentStatus.settled, PaymentStatus.released}
        return [
            p
            for p in store.list_payments()
            if p.intent.to == receiver_address and p.status in terminal
        ]
    except Exception:
        return []


def _compute_score(is_new_counterparty: bool, flag_count: int) -> int:
    """Map behavioural signals to an advisory score (0–100).

    Kept deliberately conservative — this module only adds nuance on top of the
    deterministic signals in risk_model.py; it does not gate payments alone.
    """
    if flag_count == 0:
        return 0
    score = 0
    if is_new_counterparty:
        score += 15  # modest nudge; not all new counterparties are risky
    # Each additional flag beyond new-counterparty adds weight
    extra_flags = flag_count - (1 if is_new_counterparty else 0)
    score += extra_flags * 20
    return min(score, 60)  # cap: advisory signal, not a block trigger alone
