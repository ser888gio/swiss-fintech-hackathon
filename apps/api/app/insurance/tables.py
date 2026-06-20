from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class BandPrior:
    p0: float
    n0: float


BAND_PRIORS: dict[str, BandPrior] = {
    "ELITE": BandPrior(p0=0.010, n0=80.0),
    "HIGH": BandPrior(p0=0.020, n0=50.0),
    "STANDARD": BandPrior(p0=0.045, n0=30.0),
    "HIGH_RISK": BandPrior(p0=0.090, n0=15.0),
}

RR_CATEGORY: dict[str, float] = {
    "supplier_payment": 1.00,
    "vendor_invoice": 1.05,
    "treasury_transfer": 0.90,
    "payroll": 0.95,
    "marketplace": 1.10,
}
RR_TENOR: dict[str, float] = {"instant": 0.95, "short": 1.00, "medium": 1.10, "long": 1.25}
RR_CPTY: dict[str, float] = {"low": 0.90, "standard": 1.00, "elevated": 1.15, "high": 1.35}
RR_NOVELTY: dict[bool, float] = {False: 1.00, True: 1.15}

AMOUNT_SLOPE = 0.07
VELOCITY_SLOPE = 0.05
CONC_SLOPE = 0.06

LAMBDA_EXPENSE = 0.12
LAMBDA_CAPITAL = 0.08
LAMBDA_RISK_MAX = 0.22

PD_MIN = 0.005
PD_MAX = 0.350

FLOOR: dict[str, Decimal] = {
    "merchant_default": Decimal("5.000000"),
    "lender_credit": Decimal("6.000000"),
    "principal_score": Decimal("3.000000"),
    "mandate_breach": Decimal("4.000000"),
}
LINE_CAP: dict[str, Decimal] = {
    "merchant_default": Decimal("2500.000000"),
    "lender_credit": Decimal("3000.000000"),
    "principal_score": Decimal("1200.000000"),
    "mandate_breach": Decimal("1800.000000"),
}
TICK = Decimal("0.500000")

LGD_BASIS: dict[str, Decimal] = {
    "merchant_default": Decimal("0.65"),
    "lender_credit": Decimal("0.72"),
    "principal_score": Decimal("0.30"),
    "mandate_breach": Decimal("0.40"),
}
RECOVERY_RATE: dict[str, Decimal] = {
    "merchant_default": Decimal("0.25"),
    "lender_credit": Decimal("0.18"),
    "principal_score": Decimal("0.05"),
    "mandate_breach": Decimal("0.10"),
}
LIMIT: dict[str, Decimal] = {
    "merchant_default": Decimal("50000.000000"),
    "lender_credit": Decimal("60000.000000"),
    "principal_score": Decimal("25000.000000"),
    "mandate_breach": Decimal("30000.000000"),
}

TAU_DAYS = 30.0
STEP_CAP = 0.35
PROMOTION_HYSTERESIS_COUNT = 3

