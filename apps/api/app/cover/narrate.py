"""LLM narration for cover claims — cosmetic only, never decides the payout."""

from __future__ import annotations

from .reconcile import CoverEvent
from ..schemas import CoverPolicy


def narrate_claim(event: CoverEvent, policy: CoverPolicy) -> str:
    """Return a one-paragraph human explanation of the claim divergence.

    Falls back to a deterministic template when no LLM key is configured,
    so the demo always has readable output.  The payout is already decided
    before this is called; the narration is purely cosmetic.
    """
    try:
        return _llm_narrate(event, policy)
    except Exception:
        return _template_narrate(event, policy)


def _template_narrate(event: CoverEvent, policy: CoverPolicy) -> str:
    agent = policy.agent_address[:12] + "…"
    loss = event.loss
    if event.classification == "underpayment":
        return (
            f"The AI agent ({agent}) sent an underpayment of {loss} against the expected invoice amount. "
            f"This is a hallucination event: the agent transcribed a lower value than instructed. "
            f"The Cover pool will top up the shortfall directly to the merchant."
        )
    if event.classification == "wrong_recipient":
        return (
            f"The AI agent ({agent}) routed {loss} to an incorrect recipient address. "
            f"This is a hallucination event: the agent fabricated or misread the destination. "
            f"The Cover pool will refund the treasury for the misdirected amount."
        )
    if event.classification == "non_delivery":
        return (
            f"The merchant failed to deliver goods or services after receiving payment of {loss}. "
            f"The Cover pool will refund the treasury under the non-delivery line."
        )
    return f"A covered loss event of {loss} was detected under the {event.line.value} line."


def _llm_narrate(event: CoverEvent, policy: CoverPolicy) -> str:
    import os
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("no LLM key")

    import openai
    client = openai.OpenAI(api_key=api_key)
    prompt = (
        f"An AI treasury agent insurance claim has been triggered.\n"
        f"Cover line: {event.line.value}\n"
        f"Classification: {event.classification}\n"
        f"Loss amount: {event.loss} RLUSD\n"
        f"Loss bearer: {event.loss_bearer.value}\n"
        f"Agent: {policy.agent_address}\n\n"
        f"Write one concise paragraph (2-3 sentences) explaining what happened, "
        f"why it is a covered event, and what the pool will pay. "
        f"State the exact loss amount as '{event.loss} RLUSD' — do not scale, convert, or restate it. "
        f"Be factual, not alarming. Do not mention specific XRPL addresses."
    )
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=150,
        temperature=0.3,
    )
    return resp.choices[0].message.content.strip()
