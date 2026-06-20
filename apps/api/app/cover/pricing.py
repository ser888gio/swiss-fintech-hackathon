"""Pure pricing for annual cover policies.

premium = Σ(annual_rate_per_line) × cover_cap × (term_days / 365)

No I/O. Reuses insurance/engine.py band_round and insurance/risk.py for
the non_delivery PD rate (when that line is active). hallucination is a
static config rate.
"""

from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal

from ..insurance.engine import band_round
from ..insurance.risk import AgentRisk, credibility, pd_agent
from ..insurance.tables import LAMBDA_CAPITAL, LAMBDA_EXPENSE, LAMBDA_RISK_MAX, LINE_PARAMS
from ..schemas import CoverLineKind, CoverQuote

_Q6 = Decimal("0.000001")
_Q2 = Decimal("0.01")
_YEAR = Decimal("365")


def _non_delivery_rate(r: AgentRisk, rate_min: float, rate_max: float) -> Decimal:
    """Annual non-delivery rate from the PD engine: pd × LGD × uncertainty load."""
    pd = pd_agent(r)
    z = credibility(r)
    lp = LINE_PARAMS["non_delivery"]
    load = 1.0 + LAMBDA_EXPENSE + LAMBDA_CAPITAL + LAMBDA_RISK_MAX * (1.0 - z)
    rate = max(rate_min, min(rate_max, pd * lp.lgd * load))
    return Decimal(str(round(rate, 6))).quantize(_Q6)


def _hallucination_rate(static_rate: float, rate_min: float, rate_max: float) -> Decimal:
    rate = max(rate_min, min(rate_max, static_rate))
    return Decimal(str(round(rate, 6))).quantize(_Q6)


def _receipt_hash(
    agent: str,
    cover_cap: Decimal,
    per_claim_limit: Decimal,
    term_days: int,
    premium: Decimal,
    line_rates: dict[str, str],
    pd: float,
    cred: float,
) -> str:
    payload = {
        "agent": agent,
        "cover_cap": str(cover_cap),
        "per_claim_limit": str(per_claim_limit),
        "term_days": term_days,
        "premium": str(premium),
        "line_rates": dict(sorted(line_rates.items())),
        "pd": round(pd, 8),
        "credibility": round(cred, 8),
    }
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


def price_cover(
    agent_address: str,
    score_band: str,
    cover_cap: str,          # Decimal string
    per_claim_limit: str,    # Decimal string
    term_days: int,
    lines: list[CoverLineKind],
    r: AgentRisk,
    free_capacity: Decimal,  # first_loss - Σ existing reservations
    *,
    hallucination_rate: float,
    rate_min: float,
    rate_max: float,
    premium_cap: float = 5000.0,
) -> CoverQuote:
    """Price a cover policy. Returns CoverQuote with OFFER/REVIEW/DECLINE."""
    cap_d = Decimal(cover_cap).quantize(_Q2)
    pcl_d = Decimal(per_claim_limit).quantize(_Q2)
    pd = pd_agent(r)
    cred = credibility(r)

    if not lines:
        raise ValueError("at least one cover line required")
    if pcl_d > cap_d:
        raise ValueError("per_claim_limit cannot exceed cover_cap")
    if term_days < 1 or term_days > 3650:
        raise ValueError("term_days must be between 1 and 3650")

    line_rates: dict[str, str] = {}
    total_annual_rate = Decimal("0")
    for line in lines:
        if line == CoverLineKind.hallucination:
            rate = _hallucination_rate(hallucination_rate, rate_min, rate_max)
        elif line == CoverLineKind.non_delivery:
            rate = _non_delivery_rate(r, rate_min, rate_max)
        else:
            rate = Decimal(str(rate_min)).quantize(_Q6)
        line_rates[line.value] = str(rate)
        total_annual_rate += rate

    # Prorate: annual_premium × (term_days / 365)
    prorated_premium = (total_annual_rate * cap_d * Decimal(term_days) / _YEAR).quantize(_Q2, rounding=ROUND_HALF_UP)
    premium = band_round(min(Decimal(str(premium_cap)), prorated_premium), _Q2)

    receipt = _receipt_hash(agent_address, cap_d, pcl_d, term_days, premium, line_rates, pd, cred)

    # Solvency gate: cover_cap must not exceed free pool capacity
    if cap_d > free_capacity:
        return CoverQuote(
            decision="REVIEW",
            premium=str(premium),
            line_rates=line_rates,
            pd=pd,
            credibility=cred,
            score_band=score_band,
            cover_cap=str(cap_d),
            per_claim_limit=str(pcl_d),
            term_days=term_days,
            reason=f"cover_cap {cap_d} exceeds free pool capacity {free_capacity}",
            receipt_hash=receipt,
        )

    return CoverQuote(
        decision="OFFER",
        premium=str(premium),
        line_rates=line_rates,
        pd=pd,
        credibility=cred,
        score_band=score_band,
        cover_cap=str(cap_d),
        per_claim_limit=str(pcl_d),
        term_days=term_days,
        reason=None,
        receipt_hash=receipt,
    )
