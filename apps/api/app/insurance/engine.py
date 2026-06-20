"""Deterministic pricing envelope — price() (spec §4/§7).

Pure, ordered, receipted: the statistical PD enters; a bounded, signed quote
leaves. This is the insurance analogue of policy/engine.py — the one place a
premium is decided, and (like PolicyDecision) it returns a Pydantic model so the
route can hand it straight back. The statistical core may change without
changing this contract.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from ..schemas import PremiumQuote, QuoteDecision
from . import tables
from .risk import AgentRisk, TxnFeatures, credibility, pd_txn

_Q2 = Decimal("0.01")


@dataclass(frozen=True)
class PoolState:
    """Capacity inputs for the solvency gate (spec §7/§8)."""

    first_loss: Decimal           # available first-loss capital
    currency: str = "RLUSD"


@dataclass(frozen=True)
class PricePolicy:
    """Loadings, bounds and solvency target — built from config at the boundary."""

    expense: float = tables.LAMBDA_EXPENSE
    capital: float = tables.LAMBDA_CAPITAL
    risk_margin_max: float = tables.LAMBDA_RISK_MAX
    cap: Decimal = tables.CAP
    tick: Decimal = tables.TICK
    capital_per_exposure: float = tables.CAPITAL_PER_EXPOSURE


@dataclass(frozen=True)
class QuoteContext:
    """Everything price() needs about one cover request."""

    agent_address: str
    eligible: bool
    txn: TxnFeatures
    active_lines: tuple[str, ...]
    ead: Decimal                  # transaction amount (exposure base)
    collateral: Decimal = Decimal("0")
    score_band: str | None = None


def band_round(value: Decimal, tick: Decimal) -> Decimal:
    """Round a premium to the quote tick (spec §4 band_round)."""
    if tick <= 0:
        return value
    return (value / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick


def exposure_for(line: str, ctx: QuoteContext) -> Decimal:
    """Exposure-at-default (EAD) basis per line (spec §2)."""
    if line == "merchant_default":
        return max(Decimal("0"), ctx.ead - ctx.collateral)
    if line == "principal_score":
        return ctx.ead * tables.PRINCIPAL_SCORE_EXPOSURE_FRACTION
    # lender_credit, mandate_breach: full transaction amount.
    return ctx.ead


def net_exposure(ctx: QuoteContext) -> Decimal:
    """Σ exposure·LGD across active lines — the capital the pool must back."""
    total = Decimal("0")
    for line in ctx.active_lines:
        lp = tables.LINE_PARAMS.get(line)
        if lp is None:
            continue
        total += exposure_for(line, ctx) * Decimal(str(lp.lgd))
    return total


def breaches_capacity(ctx: QuoteContext, pool: PoolState, P: PricePolicy) -> bool:
    """Solvency gate: does this exposure need more capital than the pool holds?"""
    required = net_exposure(ctx) * Decimal(str(P.capital_per_exposure))
    return required > pool.first_loss


def cover_requirement(cover_required: bool, amount_usd: float, threshold_usd: float | None) -> str:
    """Counterparty cover-requirement gate (spec §3): NONE | REQUIRED.

    A merchant/lender can mandate cover, optionally only above an amount.
    """
    if not cover_required:
        return "NONE"
    if threshold_usd is None or amount_usd >= threshold_usd:
        return "REQUIRED"
    return "NONE"


def _receipt_hash(ctx: QuoteContext, premium: Decimal, pd: float, z: float, lines: dict[str, str]) -> str:
    """Canonical, reproducible hash of the quote inputs/outputs (spec §7)."""
    payload = {
        "agent": ctx.agent_address,
        "lines": dict(sorted(lines.items())),
        "pd": round(pd, 8),
        "credibility": round(z, 8),
        "premium": str(premium),
        "ead": str(ctx.ead),
    }
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


def price(ctx: QuoteContext, r: AgentRisk, pool: PoolState, P: PricePolicy) -> PremiumQuote:
    """Price a cover request: eligibility → PP per line → loadings → floor/cap →
    band-round → solvency check → OFFER | REVIEW | DECLINE, with a receipt.
    """
    if not ctx.eligible:
        return PremiumQuote(
            decision=QuoteDecision.decline,
            premium="0",
            lines={},
            pd=0.0,
            credibility=0.0,
            reason="ineligible",
            receipt_hash=_receipt_hash(ctx, Decimal("0"), 0.0, 0.0, {}),
        )

    if not ctx.active_lines:
        return PremiumQuote(
            decision=QuoteDecision.decline,
            premium="0",
            lines={},
            pd=0.0,
            credibility=0.0,
            reason="no active cover lines",
            receipt_hash=_receipt_hash(ctx, Decimal("0"), 0.0, 0.0, {}),
        )

    pd = pd_txn(r, ctx.txn)
    z = credibility(r)
    # λ_risk shrinks with data: largest when the PD estimate is least credible.
    load = 1.0 + P.expense + P.capital + P.risk_margin_max * (1.0 - z)

    line_premiums: dict[str, str] = {}
    total = Decimal("0")
    for line in ctx.active_lines:
        lp = tables.LINE_PARAMS.get(line)
        if lp is None:
            continue
        ead = exposure_for(line, ctx)
        pure_premium = Decimal(str(pd * lp.lgd * load)) * ead
        premium_line = max(lp.floor, pure_premium).quantize(_Q2, rounding=ROUND_HALF_UP)
        line_premiums[line] = str(premium_line)
        total += premium_line

    premium = band_round(min(P.cap, total), P.tick)
    receipt = _receipt_hash(ctx, premium, pd, z, line_premiums)

    if breaches_capacity(ctx, pool, P):
        return PremiumQuote(
            decision=QuoteDecision.review,
            premium=str(premium),
            lines=line_premiums,
            pd=pd,
            credibility=z,
            reason="insufficient pool capacity for exposure",
            receipt_hash=receipt,
        )

    return PremiumQuote(
        decision=QuoteDecision.offer,
        premium=str(premium),
        lines=line_premiums,
        pd=pd,
        credibility=z,
        reason="cover offered",
        receipt_hash=receipt,
    )
