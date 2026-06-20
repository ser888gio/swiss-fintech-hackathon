from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN

from ..config import get_settings
from ..policy import engine as policy_engine
from ..schemas import (
    AgentRiskState,
    BindRequest,
    ClaimRequest,
    InsurancePayoutRecord,
    InsurancePremiumRecord,
    InsuranceQuoteRequest,
    PaymentIntent,
    PoolStatus,
    PremiumQuote,
    RouteQuote,
)
from ..tools import execution
from ..tools import vault as vault_tool
from . import engine, risk
from . import store as insurance_store

MONEY_QUANT = Decimal("0.000001")


async def quote(request: InsuranceQuoteRequest) -> PremiumQuote:
    now = datetime.now(timezone.utc)
    current = insurance_store.get_agent_risk(request.agent_address)
    if current is None:
        seeded = risk.from_band(request.score_band, now=now)
    else:
        seeded = risk.AgentRisk(
            score_band=current.score_band,
            alpha=current.alpha,
            beta=current.beta,
            n0=risk.from_band(current.score_band, now=now).n0,
            a0=risk.from_band(current.score_band, now=now).a0,
            b0=risk.from_band(current.score_band, now=now).b0,
            last_ts=current.updated_at,
        )

    pool = get_pool_status()
    return engine.price(request.txn_context, seeded, pool, _policy())


async def bind(request: BindRequest) -> InsurancePremiumRecord:
    now = datetime.now(timezone.utc)
    premium = Decimal(request.quote.premium).quantize(MONEY_QUANT, rounding=ROUND_DOWN)
    memo = execution.ComplianceMemo(
        aml_score=0,
        rule_fired=f"insurance_bind:{request.quote.decision.value}",
        receipt_hash=request.quote.receipt_hash,
    )
    result = await execution.execute_payment(
        request.job_id,
        _premium_intent(request, premium),
        _one_to_one_route(premium),
        memo=memo,
    )
    record = InsurancePremiumRecord(
        id=str(uuid.uuid4()),
        job_id=request.job_id,
        agent_address=request.agent_address,
        premium_amount=premium.to_eng_string(),
        currency=request.currency,
        tx_hash=result.tx_hash,
        explorer_url=result.explorer_url,
        score_band=request.score_band,
        created_at=now,
    )
    insurance_store.save_premium(record)
    return record


async def settle_claim(request: ClaimRequest) -> InsurancePayoutRecord:
    now = datetime.now(timezone.utc)
    claim_amount = Decimal(request.claim_amount).quantize(MONEY_QUANT, rounding=ROUND_DOWN)
    collateral = min(claim_amount, Decimal(request.collateral_available).quantize(MONEY_QUANT, rounding=ROUND_DOWN))
    pool_draw = (claim_amount - collateral).quantize(MONEY_QUANT, rounding=ROUND_DOWN)

    aml_score = request.aml_score + _collusion_penalty(request)
    decision = policy_engine.evaluate(
        amount_usd=float(claim_amount),
        aml_score=aml_score,
        sanctioned=request.sanctioned,
        threshold_usd=get_settings().policy_threshold_usd,
        flag_score=get_settings().policy_compliance_flag_score,
    )
    if decision.blocked:
        raise ClaimDeclined(decision.block_reason or "claim blocked")
    if decision.requires_approval:
        raise ClaimReviewRequired("; ".join(decision.reasons) or "claim requires review")

    slash_result = await execution.execute_payment(
        f"{request.job_id}:slash",
        _claim_intent(request, collateral, "collateral_slash"),
        _one_to_one_route(collateral),
        memo=execution.ComplianceMemo(
            aml_score=aml_score,
            rule_fired="insurance_claim_slash",
            receipt_hash=request.receipt_hash or request.job_id,
        ),
    )
    pool_result = await execution.execute_payment(
        f"{request.job_id}:pool",
        _claim_intent(request, pool_draw, "insurance_payout"),
        _one_to_one_route(pool_draw),
        memo=execution.ComplianceMemo(
            aml_score=aml_score,
            rule_fired="insurance_claim_pool",
            receipt_hash=request.receipt_hash or request.job_id,
        ),
    )

    record = InsurancePayoutRecord(
        id=str(uuid.uuid4()),
        job_id=request.job_id,
        merchant=request.merchant,
        collateral_slashed=collateral.to_eng_string(),
        pool_drawn=pool_draw.to_eng_string(),
        total_paid=claim_amount.to_eng_string(),
        currency=request.currency,
        slash_tx_hash=slash_result.tx_hash,
        pool_draw_tx_hash=pool_result.tx_hash,
        reputation_mpt_protected=True,
        created_at=now,
    )
    insurance_store.save_payout(record)

    prior = insurance_store.get_agent_risk(request.agent_address)
    base = risk.from_band(request.score_band, now=now) if prior is None else risk.AgentRisk(
        score_band=prior.score_band,
        alpha=prior.alpha,
        beta=prior.beta,
        n0=risk.from_band(prior.score_band, now=now).n0,
        a0=risk.from_band(prior.score_band, now=now).a0,
        b0=risk.from_band(prior.score_band, now=now).b0,
        last_ts=prior.updated_at,
    )
    updated = risk.update(
        base,
        defaulted=True,
        exposure_weight=max(1.0, float(claim_amount / Decimal("1000"))),
        now=now,
        tau_days=get_settings().insurance_tau_days,
    )
    insurance_store.save_agent_risk(
        AgentRiskState(
            agent_address=request.agent_address,
            score_band=updated.score_band,
            alpha=round(updated.alpha, 6),
            beta=round(updated.beta, 6),
            pd=round(updated.alpha / max(updated.alpha + updated.beta, 1e-9), 6),
            credibility=round(risk.credibility(updated), 6),
            updated_at=now,
        )
    )
    return record


def get_pool_status() -> PoolStatus:
    settings = get_settings()
    state = vault_tool.get_vault_state()
    available = Decimal(str(state["deposited"] + state["wallet_balance"])).quantize(MONEY_QUANT, rounding=ROUND_DOWN)
    paid_premiums = sum((Decimal(record.premium_amount) for record in insurance_store.list_premiums()), Decimal("0.000000"))
    paid_claims = sum((Decimal(record.pool_drawn) for record in insurance_store.list_payouts()), Decimal("0.000000"))
    return PoolStatus(
        enabled=settings.insurance_enabled,
        currency=settings.token_currency,
        deposited=_money(Decimal(str(state["deposited"]))),
        wallet_balance=_money(Decimal(str(state["wallet_balance"]))),
        available_capacity=_money(available),
        premiums_collected=_money(paid_premiums),
        claims_paid=_money(paid_claims),
    )


class ClaimReviewRequired(Exception):
    pass


class ClaimDeclined(Exception):
    pass


def _policy() -> engine.PricePolicy:
    settings = get_settings()
    return engine.PricePolicy(
        lambda_expense=Decimal(str(settings.insurance_lambda_expense)),
        lambda_capital=Decimal(str(settings.insurance_lambda_capital)),
        lambda_risk_max=Decimal(str(settings.insurance_lambda_risk_max)),
        premium_cap=Decimal(str(settings.insurance_premium_cap)).quantize(MONEY_QUANT, rounding=ROUND_DOWN),
    )


def _one_to_one_route(amount: Decimal) -> RouteQuote:
    value = float(amount)
    return RouteQuote(
        source_amount=value,
        dest_amount=value,
        rate=1.0,
        path_summary="1:1 internal treasury settlement",
        estimated_fee=0.0,
    )


def _premium_intent(request: BindRequest, premium: Decimal) -> PaymentIntent:
    treasury_address = get_settings().treasury_wallet_address or "rINSURANCE_POOL"
    return PaymentIntent(
        **{
            "from": request.agent_address,
            "to": treasury_address,
            "senderName": "Insurance premium",
            "senderCountry": "CH",
            "receiverName": "Insurance Vault",
            "receiverCountry": "CH",
            "receiverEntityType": "company",
            "purpose": "insurance_premium",
            "amount": float(premium),
            "currency": request.currency,
            "reference": request.job_id,
        }
    )


def _claim_intent(request: ClaimRequest, amount: Decimal, purpose: str) -> PaymentIntent:
    return PaymentIntent(
        **{
            "from": get_settings().treasury_wallet_address or "rTREASURY",
            "to": request.merchant,
            "senderName": "Insurance Treasury",
            "senderCountry": "CH",
            "receiverName": request.merchant_name or "Merchant",
            "receiverCountry": request.merchant_country,
            "receiverEntityType": "company",
            "purpose": purpose,
            "amount": float(amount),
            "currency": request.currency,
            "reference": request.job_id,
        }
    )


def _collusion_penalty(request: ClaimRequest) -> int:
    prior = [
        payout
        for payout in insurance_store.list_payouts()
        if payout.merchant == request.merchant and payout.job_id != request.job_id
    ]
    return 15 if len(prior) >= 2 else 0


def _money(value: Decimal) -> str:
    return value.quantize(MONEY_QUANT, rounding=ROUND_DOWN).to_eng_string()

