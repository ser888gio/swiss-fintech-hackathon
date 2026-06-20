from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN

from ..schemas import PremiumQuote, QuoteDecision
from . import risk as risk_mod
from . import tables

MONEY_QUANT = Decimal("0.000001")


@dataclass(frozen=True)
class PricePolicy:
    lambda_expense: Decimal = Decimal(str(tables.LAMBDA_EXPENSE))
    lambda_capital: Decimal = Decimal(str(tables.LAMBDA_CAPITAL))
    lambda_risk_max: Decimal = Decimal(str(tables.LAMBDA_RISK_MAX))
    premium_cap: Decimal = Decimal("5000.000000")
    tick: Decimal = tables.TICK
    pd_min: float = tables.PD_MIN
    pd_max: float = tables.PD_MAX
    floors: dict[str, Decimal] = field(default_factory=lambda: dict(tables.FLOOR))
    line_caps: dict[str, Decimal] = field(default_factory=lambda: dict(tables.LINE_CAP))
    limits: dict[str, Decimal] = field(default_factory=lambda: dict(tables.LIMIT))


def exposure_for(line: str, txn) -> Decimal:
    amount = _to_decimal(getattr(txn, "amount", "0"))
    if line == "principal_score":
        return (amount * Decimal("0.50")).quantize(MONEY_QUANT, rounding=ROUND_DOWN)
    if line == "mandate_breach":
        return (amount * Decimal("0.75")).quantize(MONEY_QUANT, rounding=ROUND_DOWN)
    return amount


def lgd_for(line: str, _ctx, _pool) -> Decimal:
    lgd = tables.LGD_BASIS[line] * (Decimal("1") - tables.RECOVERY_RATE[line])
    return lgd.quantize(MONEY_QUANT, rounding=ROUND_DOWN)


def breaches_capacity(txn, pool, policy: PricePolicy) -> bool:
    available = _pool_available(pool)
    amount = _to_decimal(getattr(txn, "amount", "0"))
    if available <= Decimal("0"):
        return True
    if amount > available:
        return True
    for line in getattr(txn, "active_lines", []):
        if amount > policy.limits.get(line, Decimal("999999999.000000")):
            return True
    return False


def band_round(value: Decimal, tick: Decimal) -> Decimal:
    if value <= Decimal("0"):
        return Decimal("0.000000")
    steps = (value / tick).quantize(Decimal("1"), rounding=ROUND_DOWN)
    rounded = (steps * tick).quantize(MONEY_QUANT, rounding=ROUND_DOWN)
    return max(rounded, tick.quantize(MONEY_QUANT, rounding=ROUND_DOWN))


def price(ctx, risk, pool, policy: PricePolicy | None = None) -> PremiumQuote:
    policy = policy or PricePolicy()
    active_lines = [line.value if hasattr(line, "value") else str(line) for line in getattr(ctx, "active_lines", [])]
    if not active_lines:
        return _quote(
            decision=QuoteDecision.decline,
            premium=Decimal("0.000000"),
            lines={},
            pd=tables.PD_MIN,
            credibility_value=risk_mod.credibility(risk),
            reason="No cover lines selected.",
            ctx=ctx,
            risk=risk,
        )

    pd = risk_mod.pd_txn(risk, ctx)
    z = risk_mod.credibility(risk)
    load = Decimal("1") + policy.lambda_expense + policy.lambda_capital + (
        policy.lambda_risk_max * Decimal(str(1.0 - z))
    )

    line_breakdown: dict[str, Decimal] = {}
    for line in active_lines:
        ead = exposure_for(line, ctx)
        if ead <= 0:
            continue
        raw = Decimal(str(pd)) * lgd_for(line, ctx, pool) * ead * load
        premium = max(policy.floors.get(line, Decimal("0.000000")), raw)
        premium = min(policy.line_caps.get(line, premium), premium).quantize(MONEY_QUANT, rounding=ROUND_DOWN)
        line_breakdown[line] = premium

    total = sum(line_breakdown.values(), Decimal("0.000000"))
    total = band_round(min(policy.premium_cap, total), policy.tick)

    if breaches_capacity(ctx, pool, policy):
        return _quote(
            decision=QuoteDecision.review,
            premium=total,
            lines=line_breakdown,
            pd=pd,
            credibility_value=z,
            reason="Pool capacity review required.",
            ctx=ctx,
            risk=risk,
        )

    if total <= Decimal("0"):
        return _quote(
            decision=QuoteDecision.decline,
            premium=Decimal("0.000000"),
            lines=line_breakdown,
            pd=pd,
            credibility_value=z,
            reason="Ineligible for insurance coverage.",
            ctx=ctx,
            risk=risk,
        )

    return _quote(
        decision=QuoteDecision.offer,
        premium=total,
        lines=line_breakdown,
        pd=pd,
        credibility_value=z,
        reason="Coverage offered.",
        ctx=ctx,
        risk=risk,
    )


def cover_requirement(intent, default_threshold_usd: float | None = None) -> str:
    threshold = getattr(intent, "cover_required_above_usd", None)
    if threshold is None:
        threshold = default_threshold_usd
    if getattr(intent, "cover_required", False):
        return "REQUIRED"
    if threshold is not None and getattr(intent, "amount", 0.0) >= threshold:
        return "REQUIRED"
    return "NONE"


def cover_gate(intent, has_cover: bool, default_threshold_usd: float | None = None) -> str:
    requirement = cover_requirement(intent, default_threshold_usd=default_threshold_usd)
    if requirement == "REQUIRED" and not has_cover:
        return "REQUIRED"
    if requirement == "REQUIRED":
        return "SATISFIED"
    return "NONE"


def _quote(*, decision, premium: Decimal, lines: dict[str, Decimal], pd: float, credibility_value: float, reason: str, ctx, risk) -> PremiumQuote:
    payload = {
        "decision": decision.value if isinstance(decision, QuoteDecision) else str(decision),
        "premium": _money(premium),
        "lines": {line: _money(value) for line, value in sorted(lines.items())},
        "pd": round(pd, 6),
        "credibility": round(credibility_value, 6),
        "reason": reason,
        "context": {
            "category": getattr(ctx, "category", ""),
            "tenorBand": getattr(ctx, "tenor_band", ""),
            "cptyBand": getattr(ctx, "cpty_band", ""),
            "firstSeen": bool(getattr(ctx, "first_seen", False)),
            "amount": str(getattr(ctx, "amount", "0")),
            "activeLines": list(getattr(ctx, "active_lines", [])),
        },
        "risk": {
            "scoreBand": getattr(risk, "score_band", ""),
            "alpha": round(getattr(risk, "alpha", 0.0), 6),
            "beta": round(getattr(risk, "beta", 0.0), 6),
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return PremiumQuote(
        decision=decision,
        premium=_money(premium),
        lines={line: _money(value) for line, value in lines.items()},
        pd=round(pd, 6),
        credibility=round(credibility_value, 6),
        reason=reason,
        receipt_hash=hashlib.sha256(canonical.encode()).hexdigest(),
    )


def _pool_available(pool) -> Decimal:
    if hasattr(pool, "available_capacity"):
        return _to_decimal(pool.available_capacity)
    deposited = _to_decimal(getattr(pool, "deposited", 0))
    wallet_balance = _to_decimal(getattr(pool, "wallet_balance", 0))
    return (deposited + wallet_balance).quantize(MONEY_QUANT, rounding=ROUND_DOWN)


def _to_decimal(value) -> Decimal:
    return Decimal(str(value)).quantize(MONEY_QUANT, rounding=ROUND_DOWN)


def _money(value: Decimal) -> str:
    return value.quantize(MONEY_QUANT, rounding=ROUND_DOWN).to_eng_string()
