from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from . import tables


@dataclass(frozen=True)
class AgentRisk:
    score_band: str
    alpha: float
    beta: float
    n0: float
    a0: float
    b0: float
    last_ts: datetime


def from_band(score_band: str, now: datetime | None = None) -> AgentRisk:
    band = score_band.upper()
    prior = tables.BAND_PRIORS.get(band, tables.BAND_PRIORS["STANDARD"])
    anchor_alpha = prior.p0 * prior.n0
    anchor_beta = (1.0 - prior.p0) * prior.n0
    ts = now or datetime.now(timezone.utc)
    return AgentRisk(
        score_band=band,
        alpha=anchor_alpha,
        beta=anchor_beta,
        n0=prior.n0,
        a0=anchor_alpha,
        b0=anchor_beta,
        last_ts=ts,
    )


def credibility(risk: AgentRisk) -> float:
    experience = max(0.0, (risk.alpha + risk.beta) - risk.n0)
    if experience <= 0:
        return 0.0
    return max(0.0, min(1.0, experience / (experience + risk.n0)))


def update(
    risk: AgentRisk,
    defaulted: bool,
    exposure_weight: float,
    now: datetime | None = None,
    tau_days: float = tables.TAU_DAYS,
) -> AgentRisk:
    ts = now or datetime.now(timezone.utc)
    age_days = max(0.0, (ts - risk.last_ts).total_seconds() / 86400.0)
    decay = math.exp(-age_days / tau_days) if tau_days > 0 else 0.0

    alpha = risk.a0 + (risk.alpha - risk.a0) * decay
    beta = risk.b0 + (risk.beta - risk.b0) * decay
    weight = max(0.0, exposure_weight)
    if defaulted:
        alpha += weight
    else:
        beta += weight

    return AgentRisk(
        score_band=risk.score_band,
        alpha=alpha,
        beta=beta,
        n0=risk.n0,
        a0=risk.a0,
        b0=risk.b0,
        last_ts=ts,
    )


def pd_txn(risk: AgentRisk, txn) -> float:
    base_pd = risk.alpha / max(risk.alpha + risk.beta, 1e-9)
    category = tables.RR_CATEGORY.get(getattr(txn, "category", "supplier_payment"), 1.0)
    tenor = tables.RR_TENOR.get(getattr(txn, "tenor_band", "short"), 1.0)
    counterparty = tables.RR_CPTY.get(getattr(txn, "cpty_band", "standard"), 1.0)
    novelty = tables.RR_NOVELTY.get(bool(getattr(txn, "first_seen", False)), 1.0)
    ctx_adj = 1.0 + (
        getattr(txn, "amount_z", 0.0) * tables.AMOUNT_SLOPE
        + getattr(txn, "velocity_z", 0.0) * tables.VELOCITY_SLOPE
        + getattr(txn, "concentration_z", 0.0) * tables.CONC_SLOPE
    )
    ctx_adj = max(0.50, ctx_adj)
    pd = base_pd * category * tenor * counterparty * novelty * ctx_adj
    return max(tables.PD_MIN, min(tables.PD_MAX, pd))

