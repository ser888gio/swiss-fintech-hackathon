"""Insurance calibration tables (spec §9).

Every tunable lives here so risk appetite is set without touching the engine
code. Cold-start defaults are seeded from proxy analogues (consumer/SME credit)
per spec §10; they are overridden at the boundary by `PricePolicy` built from
config in `app/tools/insurance.py`.

Probabilities / multipliers are plain floats; money (floors, caps, limits) is
Decimal so premium math stays exact.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


# ── Band priors (per certified ScoreBand) ─────────────────────────────────────

@dataclass(frozen=True)
class BandPrior:
    """Prior default rate p0 and prior strength n0 (pseudo-count) for a band.

    ELITE: low p0, high n0 (confident it's safe). HIGH_RISK: high p0, low n0
    (uncertain and risky). The agent posterior starts at this prior and moves
    toward realized experience as credibility (Z) rises.
    """

    p0: float
    n0: float


BAND_PRIORS: dict[str, BandPrior] = {
    "ELITE": BandPrior(p0=0.005, n0=80.0),
    "HIGH": BandPrior(p0=0.015, n0=40.0),
    "STANDARD": BandPrior(p0=0.035, n0=20.0),
    "HIGH_RISK": BandPrior(p0=0.090, n0=8.0),
}
DEFAULT_BAND = "STANDARD"


# ── Relative-risk tables (portfolio-calibrated, spec §5) ──────────────────────
# Each table carries a "default" key so an unknown bucket falls back to neutral.

RR_CATEGORY: dict[str, float] = {
    "merchant_payment": 1.0,
    "supplier_payment": 0.85,
    "loan_repayment": 1.25,
    "service_payment": 0.90,
    "data_lookup": 0.80,
    "default": 1.0,
}

RR_TENOR: dict[str, float] = {
    "instant": 0.80,
    "lt_30d": 0.95,
    "30_90d": 1.10,
    "gt_90d": 1.35,
    "default": 1.0,
}

RR_CPTY: dict[str, float] = {
    "verified": 0.85,
    "known": 1.0,
    "new": 1.20,
    "unverified": 1.40,
    "default": 1.0,
}

# Novelty: a never-before-seen transaction shape costs more than a repeat.
NOVELTY_FIRST_SEEN = 1.25
NOVELTY_REPEAT = 0.95


# ── Context slopes (fast signals, spec §5) ────────────────────────────────────

AMOUNT_SLOPE = 0.05      # premium sensitivity to amount-vs-typical z-score
VELOCITY_SLOPE = 0.04    # sensitivity to recent transaction velocity
CONC_SLOPE = 0.06        # sensitivity to counterparty/sector concentration


# ── Loadings (spec §4) ────────────────────────────────────────────────────────

LAMBDA_EXPENSE = 0.05    # operating cost of running the cover
LAMBDA_CAPITAL = 0.08    # cost of capital backing the exposure
LAMBDA_RISK_MAX = 0.30   # max uncertainty margin; shrinks to 0 as Z → 1


# ── Bounds ────────────────────────────────────────────────────────────────────

PD_MIN = 0.0005
PD_MAX = 0.95


# ── Per-line parameters (the four covered lines, spec §2) ─────────────────────

@dataclass(frozen=True)
class LineParams:
    """Per-line exposure/loss basis.

    lgd            — loss-given-default as a fraction of exposure (EAD)
    floor          — minimum premium charged for an active line
    limit          — maximum payout the pool will make on this line
    recovery_rate  — fraction of the post-recovery shortfall the pool pays
    """

    lgd: float
    floor: Decimal
    limit: Decimal
    recovery_rate: float


LINE_PARAMS: dict[str, LineParams] = {
    # peril: agent doesn't pay for delivered goods — net of agent collateral.
    "merchant_default": LineParams(
        lgd=0.70, floor=Decimal("0.50"), limit=Decimal("100000"), recovery_rate=0.90
    ),
    # peril: agent doesn't repay working capital — loss after first-loss capital.
    "lender_credit": LineParams(
        lgd=0.60, floor=Decimal("0.75"), limit=Decimal("250000"), recovery_rate=0.90
    ),
    # peril: a default would burn the principal's standing — pool absorbs it.
    "principal_score": LineParams(
        lgd=0.20, floor=Decimal("0.25"), limit=Decimal("25000"), recovery_rate=1.0
    ),
    # peril: wrong payee / amount / overspend — highest moral-hazard weight.
    "mandate_breach": LineParams(
        lgd=0.95, floor=Decimal("1.00"), limit=Decimal("100000"), recovery_rate=0.85
    ),
}

# Fraction of transaction amount used as the exposure base for principal-score
# protection (the repricing/credit impact avoided, not the cash amount).
PRINCIPAL_SCORE_EXPOSURE_FRACTION = Decimal("0.10")


# ── Solvency / envelope bounds ────────────────────────────────────────────────

CAP = Decimal("5000")            # max total premium per quote (spec §4)
TICK = Decimal("0.01")           # quote band-rounding tick
CAPITAL_PER_EXPOSURE = 0.15      # first-loss capital required per unit net exposure


# ── Experience-rating loop (spec §6) ──────────────────────────────────────────

TAU_DAYS = 120.0                 # recency half-life for posterior decay
STEP_CAP = 0.35                  # max per-event premium move (±35%)
EXPOSURE_WEIGHT_MIN = 0.25       # clamp on exposure-weighted updates
EXPOSURE_WEIGHT_MAX = 4.0
