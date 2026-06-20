"""Statistical core — PD estimation & the experience-rating loop (spec §5/§6).

Pure functions, no I/O. Each agent's default propensity is a Beta(alpha, beta)
posterior initialized from its certified ScoreBand prior. The posterior mean is,
by construction, a credibility blend of the band prior and the agent's realized
rate — so "weight the agent's record against its band prior" falls out for free.

PD and credibility are floats (probabilities); the deterministic envelope in
engine.py converts to Decimal at the premium boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import exp

from .tables import (
    AMOUNT_SLOPE,
    BAND_PRIORS,
    CONC_SLOPE,
    DEFAULT_BAND,
    EXPOSURE_WEIGHT_MAX,
    EXPOSURE_WEIGHT_MIN,
    NOVELTY_FIRST_SEEN,
    NOVELTY_REPEAT,
    PD_MAX,
    PD_MIN,
    RR_CATEGORY,
    RR_CPTY,
    RR_TENOR,
    TAU_DAYS,
    VELOCITY_SLOPE,
)


@dataclass(frozen=True)
class AgentRisk:
    """An agent's default-propensity posterior, Beta(alpha, beta).

    alpha/beta are pseudo-defaults / pseudo-successes (prior + observed). a0/b0
    are the band-prior anchor that recency decay forgets back toward; n0 is the
    prior strength used to compute credibility.
    """

    alpha: float
    beta: float
    n0: float
    a0: float
    b0: float
    last_ts: float  # epoch seconds of the last update
    score_band: str = "STANDARD"  # certified band the prior was seeded from


@dataclass(frozen=True)
class TxnFeatures:
    """Transaction-shape inputs to the relative-risk multiplier (spec §5)."""

    category: str = "merchant_payment"
    tenor_band: str = "lt_30d"
    cpty_band: str = "known"
    first_seen: bool = False
    amount_z: float = 0.0
    velocity_z: float = 0.0
    concentration_z: float = 0.0


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _to_ts(value: float | datetime) -> float:
    """Normalize a timestamp (epoch seconds or aware datetime) to epoch seconds.

    Callers (tests, the orchestrator, persistence) pass datetimes; the recency
    decay math is in seconds. Accept both so a datetime never reaches arithmetic.
    """
    if isinstance(value, datetime):
        return value.timestamp()
    return float(value)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def from_band(score_band: str | None, now: float | datetime | None = None) -> AgentRisk:
    """Seed a fresh posterior from the certified ScoreBand prior (cold start)."""
    band = (score_band or DEFAULT_BAND).upper()
    prior = BAND_PRIORS.get(band, BAND_PRIORS[DEFAULT_BAND])
    a0 = prior.p0 * prior.n0
    b0 = (1.0 - prior.p0) * prior.n0
    ts = _to_ts(now) if now is not None else _now_ts()
    return AgentRisk(alpha=a0, beta=b0, n0=prior.n0, a0=a0, b0=b0, last_ts=ts, score_band=band)


def credibility(r: AgentRisk) -> float:
    """Z ∈ [0, 1]: 0 = all band prior, 1 = all the agent's own experience."""
    observed = max(0.0, (r.alpha + r.beta) - r.n0)
    denom = observed + r.n0
    return observed / denom if denom > 0 else 0.0


def pd_agent(r: AgentRisk) -> float:
    """Posterior mean default rate for the agent (band-blended)."""
    total = r.alpha + r.beta
    return r.alpha / total if total > 0 else 0.0


def pd_txn(r: AgentRisk, txn: TxnFeatures) -> float:
    """PD for this agent on this transaction shape (spec §5), clamped."""
    base = pd_agent(r)
    rr = (
        RR_CATEGORY.get(txn.category, RR_CATEGORY["default"])
        * RR_TENOR.get(txn.tenor_band, RR_TENOR["default"])
        * RR_CPTY.get(txn.cpty_band, RR_CPTY["default"])
        * (NOVELTY_FIRST_SEEN if txn.first_seen else NOVELTY_REPEAT)
    )
    adj = 1.0 + AMOUNT_SLOPE * txn.amount_z + VELOCITY_SLOPE * txn.velocity_z + CONC_SLOPE * txn.concentration_z
    adj = max(0.1, adj)  # context can never drive PD non-positive
    return _clamp(base * rr * adj, PD_MIN, PD_MAX)


def update(
    r: AgentRisk,
    *,
    defaulted: bool,
    exposure_weight: float,
    now: float | datetime | None = None,
    tau_days: float = TAU_DAYS,
) -> AgentRisk:
    """Apply one outcome to the posterior (spec §6).

    1. Recency decay: exponentially forget observed mass back toward the band
       anchor, so the price reflects *recent* conduct.
    2. Exposure-weighted outcome: a default on a large ticket moves PD more than
       a trivial one (weight clamped to keep the loop stable).
    """
    now_ts = _to_ts(now) if now is not None else _now_ts()
    last_ts = _to_ts(r.last_ts)
    decay = exp(-((now_ts - last_ts) / 86400.0) / tau_days) if tau_days > 0 else 1.0
    a = r.a0 + (r.alpha - r.a0) * decay
    b = r.b0 + (r.beta - r.b0) * decay
    w = _clamp(exposure_weight, EXPOSURE_WEIGHT_MIN, EXPOSURE_WEIGHT_MAX)
    if defaulted:
        a += w
    else:
        b += w
    return AgentRisk(alpha=a, beta=b, n0=r.n0, a0=r.a0, b0=r.b0, last_ts=now_ts, score_band=r.score_band)
