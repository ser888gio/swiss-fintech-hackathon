"""Insurance tool — premium binding & claim payout (ARS Pillar 3, spec §7/§8).

The deterministic pricing envelope lives in app/insurance/engine.py (pure). This
tool is the async settlement layer: it builds the quote context from agent risk
+ pool capacity, settles the premium into the Insurance Vault, and runs the
claim payout waterfall — reusing the same mock/real XRPL split, audit log, and
spend-reservation idempotency as the other ARS pillars (lending, trade_finance).

Determinism boundary: the LLM never calls this. The premium is decided by
engine.price(); the payout is gated by policy.engine.evaluate() plus a collusion
guard before any capital moves.

Mock mode (settings.use_mock_xrpl): in-memory state, deterministic tx hashes, no
network — the full quote → bind → claim round-trip runs offline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from .. import db, xrpl_client
from ..config import get_settings
from ..insurance import engine, risk
from ..insurance.engine import PoolState, PricePolicy, QuoteContext
from ..insurance.risk import AgentRisk, TxnFeatures
from ..insurance.tables import LINE_PARAMS
from ..policy import engine as policy_engine
from . import execution
from . import vault as vault_tool
from ..schemas import (
    AgentRiskState,
    BindRequest,
    CapitalDepositRequest,
    CapitalWithdrawRequest,
    ClaimRequest,
    GuardrailResult,
    InsurancePayoutRecord,
    InsurancePremiumRecord,
    InsuranceQuoteRequest,
    LpPosition,
    PoolStatus,
    PremiumQuote,
    QuoteDecision,
    TxnContext,
)

log = logging.getLogger(__name__)

_Q2 = Decimal("0.01")

# ── In-memory state (mock + real-mode cache) ──────────────────────────────────
_agent_risk: dict[str, AgentRisk] = {}        # agent_address → posterior
_bands: dict[str, str | None] = {}            # agent_address → score band used
_premiums: list[InsurancePremiumRecord] = []
_payouts: list[InsurancePayoutRecord] = []
_pool = {"premiums": Decimal("0"), "payouts": Decimal("0")}
_payout_pairs: dict[tuple[str, str], int] = {}   # (agent, merchant) → payout count
_lp_capital: dict[str, Decimal] = {}             # LP address → capital contributed


def reset_mock_state() -> None:
    _agent_risk.clear()
    _bands.clear()
    _premiums.clear()
    _payouts.clear()
    _payout_pairs.clear()
    _lp_capital.clear()
    _pool["premiums"] = Decimal("0")
    _pool["payouts"] = Decimal("0")
    # Reset the shared XLS-65 vault so the first-loss pool starts clean.
    vault_tool._state.update({
        "vault_id": None,
        "deposited": 0.0,
        "shares": 0.0,
        "wallet_balance": 50_000.0,
        "operations": [],
    })


# ── Boundary builders (config → pure dataclasses) ─────────────────────────────

def _price_policy(settings) -> PricePolicy:
    return PricePolicy(
        expense=settings.insurance_lambda_expense,
        capital=settings.insurance_lambda_capital,
        risk_margin_max=settings.insurance_lambda_risk_max,
        cap=Decimal(str(settings.insurance_premium_cap_usd)),
        capital_per_exposure=settings.insurance_capital_per_exposure,
    )


def _lp_total() -> Decimal:
    return sum(_lp_capital.values(), Decimal("0"))


def _pool_state(settings) -> PoolState:
    base = Decimal(str(settings.insurance_pool_first_loss_usd))
    first_loss = base + _lp_total() + _pool["premiums"] - _pool["payouts"]
    return PoolState(first_loss=max(Decimal("0"), first_loss), currency=settings.token_currency)


async def _ensure_vault(settings) -> str:
    """Return the Insurance Vault id, provisioning an XLS-65 vault on first use.

    The same Single Asset Vault tool the treasury uses backs the first-loss pool,
    so premiums (VaultDeposit) and payouts (VaultWithdraw) are real on-ledger
    operations. insurance_vault_address overrides the auto-provisioned id.
    """
    vault_id = settings.insurance_vault_address or settings.vault_id or vault_tool.get_vault_state().get("vault_id")
    if vault_id:
        return vault_id
    result = await vault_tool.create_vault(
        settings.token_currency,
        settings.token_issuer_address or "rMOCK_ISSUER",
    )
    return result.vault_id


def _txn_features(txn: TxnContext) -> TxnFeatures:
    return TxnFeatures(
        category=txn.category,
        tenor_band=txn.tenor_band,
        cpty_band=txn.cpty_band,
        first_seen=txn.first_seen,
        amount_z=txn.amount_z,
        velocity_z=txn.velocity_z,
        concentration_z=txn.concentration_z,
    )


def get_or_seed_risk(agent_address: str, score_band: str | None) -> AgentRisk:
    """Return the agent's posterior, seeding it from the band prior on first use."""
    r = _agent_risk.get(agent_address)
    if r is None:
        r = risk.from_band(score_band)
        _agent_risk[agent_address] = r
        _bands[agent_address] = score_band
    elif score_band and _bands.get(agent_address) is None:
        _bands[agent_address] = score_band
    return r


# ── Quote (pure pricing, no settlement) ───────────────────────────────────────

def quote(req: InsuranceQuoteRequest) -> PremiumQuote:
    """Price a cover request via the deterministic envelope. No I/O side effects."""
    settings = get_settings()
    r = get_or_seed_risk(req.agent_address, req.score_band)
    ctx = QuoteContext(
        agent_address=req.agent_address,
        eligible=settings.insurance_enabled,
        txn=_txn_features(req.txn),
        active_lines=tuple(l.value for l in req.active_lines),
        ead=Decimal(req.amount),
        collateral=Decimal(req.collateral),
        score_band=req.score_band or _bands.get(req.agent_address),
    )
    return engine.price(ctx, r, _pool_state(settings), _price_policy(settings))


# ── Bind (settle the premium into the Insurance Vault) ────────────────────────

async def bind(req: BindRequest) -> InsurancePremiumRecord:
    """Re-quote then settle the premium. Only an OFFER binds; REVIEW/DECLINE raise."""
    settings = get_settings()
    if not settings.insurance_enabled:
        raise InsuranceDisabled("insurance_enabled is False")

    # Per-party compliance: the agent must pass G1 KYA (advisory unless
    # insurance_enforce_kya) and G2 sanctions (always hard) to bind cover.
    trail, blocking = await _party_guardrails(agent_address=req.agent_address)
    if blocking is not None:
        raise GuardrailRefused(blocking.name, blocking.reason or blocking.rule_fired or "blocked", trail)

    quote_req = InsuranceQuoteRequest(
        agent_address=req.agent_address,
        amount=req.amount,
        currency=req.currency,
        score_band=req.score_band,
        active_lines=req.active_lines,
        collateral=req.collateral,
        txn=req.txn,
        job_id=req.job_id,
    )
    q = quote(quote_req)
    if q.decision is not QuoteDecision.OFFER:
        raise CoverUnavailable(q.decision.value, q.reason or "cover not offered")

    premium = Decimal(q.premium)
    # Settle the premium on-ledger into the first-loss pool. Vault mode uses an
    # XLS-65 VaultDeposit (Devnet); Payment mode sends a token Payment to the pool
    # account (works on any network) — both return a real explorer link.
    tx_hash, explorer_url = await _settle_premium(req, premium, settings)

    now = datetime.now(timezone.utc)
    record = InsurancePremiumRecord(
        id=str(uuid.uuid4()),
        job_id=req.job_id,
        agent_address=req.agent_address,
        premium_amount=q.premium,
        currency=settings.token_currency,   # actual on-ledger settlement asset
        tx_hash=tx_hash,
        explorer_url=explorer_url,
        score_band=q.score_band,
        guardrail_trail=trail,
        created_at=now,
    )
    _premiums.append(record)
    _pool["premiums"] += premium
    _emit_audit(
        "insurance_premium_bound",
        {
            "job_id": req.job_id,
            "agent_address": req.agent_address,
            "premium": q.premium,
            "currency": req.currency,
            "receipt_hash": q.receipt_hash,
            "tx_hash": tx_hash,
            "explorer_url": explorer_url,
        },
    )
    _schedule(_persist_premium(record))
    return record


# ── Claim (payout waterfall on a covered default) ─────────────────────────────

async def settle_claim(req: ClaimRequest) -> InsurancePayoutRecord:
    """Settle a claim: recover collateral → draw first-loss → pay the merchant.

    Gated by policy.engine.evaluate() (limit/AML) and a collusion guard before
    any capital moves. Then reprices the agent posterior with a default update.
    """
    settings = get_settings()
    if not settings.insurance_enabled:
        raise InsuranceDisabled("insurance_enabled is False")

    lp = LINE_PARAMS[req.line.value]
    loss = Decimal(req.loss)
    collateral = Decimal(req.collateral)

    # Recovery first (collateral), then the pool covers the residual shortfall.
    collateral_recovery = min(collateral, loss).quantize(_Q2, rounding=ROUND_HALF_UP)
    shortfall = max(Decimal("0"), loss - collateral_recovery)
    payout = min(lp.limit, Decimal(str(lp.recovery_rate)) * shortfall).quantize(_Q2, rounding=ROUND_HALF_UP)
    pool = _pool_state(settings)
    pool_drawn = min(payout, pool.first_loss).quantize(_Q2, rounding=ROUND_HALF_UP)

    # Build the full payout guardrail trail: per-party (G1/G2), the decide(PAYOUT)
    # policy gate, and the collusion guard — then enforce the hard blocks.
    trail, party_block = await _party_guardrails(agent_address=req.agent_address, counterparty=req.merchant)
    decision = policy_engine.evaluate(
        float(payout),
        aml_score=0,
        sanctioned=False,
        threshold_usd=settings.policy_threshold_usd,
        flag_score=settings.policy_compliance_flag_score,
    )
    trail.append(GuardrailResult(
        name="G6_payout",
        passed=not decision.blocked,
        rule_fired=decision.rule_fired,
        reason="; ".join(decision.reasons) if decision.reasons else None,
    ))
    collusion = _is_collusion(req.agent_address, req.merchant)
    trail.append(GuardrailResult(
        name="G2b_collusion",
        passed=not collusion,
        rule_fired="collusion" if collusion else None,
        reason="repeated payouts between agent and counterparty" if collusion else None,
    ))
    if party_block is not None:
        raise PayoutRefused(party_block.reason or party_block.rule_fired or "payout blocked")
    if decision.blocked:
        raise PayoutRefused(decision.block_reason or "payout blocked by policy")
    if collusion:
        raise PayoutRefused("collusion pattern: repeated payouts between agent and merchant")

    # Settle the payout: the pool portion is drawn on-ledger (XLS-65 VaultWithdraw
    # in vault mode, or a token Payment to the merchant in Payment mode). Agent
    # collateral slashing is an off-vault track (mock hash in mock mode).
    slash_tx, draw_tx, draw_explorer = await _settle_payout(req, collateral_recovery, pool_drawn, settings)

    now = datetime.now(timezone.utc)
    record = InsurancePayoutRecord(
        id=str(uuid.uuid4()),
        job_id=req.job_id,
        merchant=req.merchant,
        collateral_slashed=str(collateral_recovery),
        pool_drawn=str(pool_drawn),
        total_paid=str((collateral_recovery + pool_drawn).quantize(_Q2)),
        currency=settings.token_currency,   # actual on-ledger settlement asset
        slash_tx_hash=slash_tx,
        pool_draw_tx_hash=draw_tx,
        explorer_url=draw_explorer,
        reputation_mpt_protected=True,
        guardrail_trail=trail,
        created_at=now,
    )
    _payouts.append(record)
    _pool["payouts"] += pool_drawn
    _payout_pairs[(req.agent_address, req.merchant)] = _payout_pairs.get((req.agent_address, req.merchant), 0) + 1

    # Reprice: the default moves the posterior up, exposure-weighted by the loss.
    record_outcome(
        req.agent_address,
        defaulted=True,
        exposure_weight=_exposure_weight(loss, settings),
        score_band=_bands.get(req.agent_address),
    )

    _emit_audit(
        "insurance_payout",
        {
            "job_id": req.job_id,
            "merchant": req.merchant,
            "line": req.line.value,
            "collateral_slashed": record.collateral_slashed,
            "pool_drawn": record.pool_drawn,
            "total_paid": record.total_paid,
            "slash_tx_hash": slash_tx,
            "pool_draw_tx_hash": draw_tx,
        },
    )
    _schedule(_persist_payout(record))
    return record


# ── Experience-rating outcome (spec §6) ───────────────────────────────────────

def record_outcome(
    agent_address: str,
    *,
    defaulted: bool,
    exposure_weight: float,
    score_band: str | None = None,
) -> AgentRisk:
    """Apply one outcome to the agent posterior and persist it."""
    settings = get_settings()
    r = get_or_seed_risk(agent_address, score_band)
    updated = risk.update(
        r,
        defaulted=defaulted,
        exposure_weight=exposure_weight,
        tau_days=settings.insurance_tau_days,
    )
    _agent_risk[agent_address] = updated
    _schedule(_persist_risk(agent_address, updated, _bands.get(agent_address)))
    return updated


# ── Read models ───────────────────────────────────────────────────────────────

def get_agent_risk_state(agent_address: str) -> AgentRiskState | None:
    r = _agent_risk.get(agent_address)
    if r is None:
        return None
    return AgentRiskState(
        agent_address=agent_address,
        score_band=_bands.get(agent_address),
        alpha=r.alpha,
        beta=r.beta,
        pd=risk.pd_agent(r),
        credibility=risk.credibility(r),
        updated_at=datetime.now(timezone.utc),
    )


def get_pool_status() -> PoolStatus:
    settings = get_settings()
    base = Decimal(str(settings.insurance_pool_first_loss_usd))
    lp_total = _lp_total()
    first_loss = max(Decimal("0"), base + lp_total + _pool["premiums"] - _pool["payouts"])
    denom = base + lp_total
    ratio = float(first_loss / denom) if denom > 0 else 0.0
    vault_balance = Decimal(str(vault_tool.get_vault_state().get("deposited") or 0))
    return PoolStatus(
        first_loss=str(first_loss),
        currency=settings.token_currency,
        premiums_collected=str(_pool["premiums"]),
        payouts_made=str(_pool["payouts"]),
        capacity_ratio=ratio,
        vault_balance=str(vault_balance),
        lp_capital=str(lp_total),
    )


# ── Capital Provider (LP) ─────────────────────────────────────────────────────

async def deposit_capital(req: CapitalDepositRequest) -> LpPosition:
    """An LP contributes first-loss capital to the pool (G1/G2 gated)."""
    settings = get_settings()
    if not settings.insurance_enabled:
        raise InsuranceDisabled("insurance_enabled is False")
    trail, blocking = await _party_guardrails(agent_address=req.lp_address)
    if blocking is not None:
        raise GuardrailRefused(blocking.name, blocking.reason or blocking.rule_fired or "blocked", trail)

    amount = Decimal(req.amount)
    tx_hash, explorer_url = await _settle_capital(_pool_account(settings), amount, req.lp_address, "capital_in", settings)
    _lp_capital[req.lp_address] = _lp_capital.get(req.lp_address, Decimal("0")) + amount
    _emit_audit("insurance_capital_deposit", {"lp_address": req.lp_address, "amount": req.amount, "tx_hash": tx_hash})
    return _lp_position(req.lp_address, tx_hash=tx_hash, explorer_url=explorer_url, trail=trail)


async def withdraw_capital(req: CapitalWithdrawRequest) -> LpPosition:
    """An LP recalls capital (clamped to its contributed balance)."""
    settings = get_settings()
    if not settings.insurance_enabled:
        raise InsuranceDisabled("insurance_enabled is False")
    held = _lp_capital.get(req.lp_address, Decimal("0"))
    amount = min(Decimal(req.amount), held).quantize(_Q2, rounding=ROUND_HALF_UP)
    tx_hash, explorer_url = (None, None)
    if amount > 0:
        tx_hash, explorer_url = await _settle_capital(req.lp_address, amount, req.lp_address, "capital_out", settings)
        _lp_capital[req.lp_address] = held - amount
    _emit_audit("insurance_capital_withdraw", {"lp_address": req.lp_address, "amount": str(amount), "tx_hash": tx_hash})
    return _lp_position(req.lp_address, tx_hash=tx_hash, explorer_url=explorer_url)


def list_positions() -> list[LpPosition]:
    return [_lp_position(addr) for addr, cap in _lp_capital.items() if cap > 0]


def _lp_position(
    lp_address: str, *, tx_hash: str | None = None, explorer_url: str | None = None,
    trail: list[GuardrailResult] | None = None,
) -> LpPosition:
    capital = _lp_capital.get(lp_address, Decimal("0"))
    total = _lp_total()
    share = float(capital / total) if total > 0 else 0.0
    return LpPosition(
        lp_address=lp_address,
        capital=str(capital),
        share_pct=share,
        currency=get_settings().token_currency,
        tx_hash=tx_hash,
        explorer_url=explorer_url,
        guardrail_trail=trail or [],
        updated_at=datetime.now(timezone.utc),
    )


async def _settle_capital(
    destination: str, amount: Decimal, lp_address: str, kind: str, settings
) -> tuple[str | None, str | None]:
    """Settle an LP capital movement on-ledger (mock hash, or a real Payment)."""
    if settings.use_mock_xrpl:
        return xrpl_client.mock_tx_hash(kind, f"{lp_address}:{amount}"), None
    return await _pay(destination, amount, lp_address, kind, settings)


# ── Per-party compliance guardrails (G1 KYA + G2 sanctions) ───────────────────

async def _party_guardrails(
    *, agent_address: str, counterparty: str | None = None, counterparty_name: str | None = None,
) -> tuple[list[GuardrailResult], GuardrailResult | None]:
    """Run G1 KYA + G2 sanctions for a party action.

    Returns (trail, blocking): `blocking` is the first hard-failing guardrail
    (G2 sanctions always; G1 KYA only when insurance_enforce_kya), or None.
    """
    settings = get_settings()
    trail: list[GuardrailResult] = []
    blocking: GuardrailResult | None = None

    if settings.credential_kyc_enabled:
        from . import credentials
        cred = await credentials.verify_kyc(agent_address)
        g1 = GuardrailResult(
            name="G1_kya",
            passed=cred.verified,
            rule_fired=None if cred.verified else "kya_unverified",
            reason=None if cred.verified else cred.reason,
        )
        trail.append(g1)
        if not g1.passed and settings.insurance_enforce_kya:
            blocking = blocking or g1

    sanctioned = _sanctions_hit(agent_address, None) or (
        counterparty is not None and _sanctions_hit(counterparty, counterparty_name)
    )
    g2 = GuardrailResult(
        name="G2_sanctions",
        passed=not sanctioned,
        rule_fired="sanctions_block" if sanctioned else None,
        reason="party on sanctions list" if sanctioned else None,
    )
    trail.append(g2)
    if not g2.passed:
        blocking = blocking or g2

    return trail, blocking


def _sanctions_hit(address: str, name: str | None) -> bool:
    from . import compliance
    if address in compliance.SANCTIONED_ACCOUNTS:
        return True
    if name and name.lower() in compliance.SANCTIONED_NAMES:
        return True
    return False


def list_premiums() -> list[InsurancePremiumRecord]:
    return sorted(_premiums, key=lambda p: p.created_at, reverse=True)


def list_payouts() -> list[InsurancePayoutRecord]:
    return sorted(_payouts, key=lambda p: p.created_at, reverse=True)


# ── On-ledger settlement (mock / vault / payment) ─────────────────────────────

async def _settle_premium(req: BindRequest, premium: Decimal, settings) -> tuple[str, str | None]:
    """Settle the premium into the pool. Returns (tx_hash, explorer_url)."""
    if settings.use_mock_xrpl:
        return xrpl_client.mock_tx_hash("insurance_premium", req.job_id), None
    if settings.insurance_use_vault:
        vault_id = await _ensure_vault(settings)
        deposit = await vault_tool.deposit(vault_id, float(premium))
        return deposit.tx_hash, deposit.explorer_url
    return await _pay(_pool_account(settings), premium, req.job_id, "insurance_premium", settings)


async def _settle_payout(
    req: ClaimRequest, collateral_recovery: Decimal, pool_drawn: Decimal, settings
) -> tuple[str | None, str | None, str | None]:
    """Settle the payout. Returns (slash_tx, pool_draw_tx, pool_draw_explorer)."""
    slash_tx = (
        xrpl_client.mock_tx_hash("insurance_slash", req.job_id)
        if collateral_recovery > 0 and settings.use_mock_xrpl
        else None
    )
    if pool_drawn <= 0:
        return slash_tx, None, None
    if settings.use_mock_xrpl:
        return slash_tx, xrpl_client.mock_tx_hash("insurance_payout", req.job_id), None
    if settings.insurance_use_vault:
        vault_id = await _ensure_vault(settings)
        withdrawal = await vault_tool.withdraw(vault_id, float(pool_drawn))
        return None, withdrawal.tx_hash, withdrawal.explorer_url
    draw_tx, explorer = await _pay(req.merchant, pool_drawn, req.job_id, "insurance_payout", settings)
    return None, draw_tx, explorer


async def _pay(destination: str, amount: Decimal, job_id: str, kind: str, settings) -> tuple[str, str | None]:
    """Submit a real token Payment for an insurance settlement (Payment mode).

    Applies the same testnet settlement scale as the payment path so the
    on-ledger amount is fundable, and anchors the job id in a Memo + SourceTag.
    """
    if not destination:
        raise InsuranceConfigError(
            "insurance_vault_address (pool account) must be set for real-mode insurance settlement"
        )
    from ..ledger import Ledger
    from xrpl.models.transactions import Memo, Payment

    ledger = Ledger(settings)
    wallet = ledger.treasury_wallet
    memo_data = json.dumps({kind: job_id}, separators=(",", ":"))
    on_ledger = execution.scaled_settlement(float(amount), settings)
    tx = Payment(
        account=wallet.address,
        destination=destination,
        amount=xrpl_client.token_amount(settings.token_currency, on_ledger, settings),
        source_tag=settings.insurance_source_tag,
        memos=[Memo(
            memo_type="insurance/v1".encode().hex().upper(),
            memo_data=memo_data.encode().hex().upper(),
        )],
    )
    result = await ledger.submit(tx, wallet)
    tx_hash = result["hash"]
    return tx_hash, xrpl_client.explorer_tx_url_for(tx_hash, settings.xrpl_endpoint)


def _pool_account(settings) -> str:
    return settings.insurance_vault_address


# ── Guards & helpers ──────────────────────────────────────────────────────────

def _is_collusion(agent_address: str, merchant: str) -> bool:
    """Flag a fabricated-default pattern: repeated payouts on one agent↔merchant pair."""
    return _payout_pairs.get((agent_address, merchant), 0) >= 2


def _exposure_weight(loss: Decimal, settings) -> float:
    """Weight a default by loss size relative to the policy reference ticket."""
    ref = Decimal(str(settings.policy_threshold_usd or 10_000))
    if ref <= 0:
        return 1.0
    return max(0.25, min(4.0, float(loss / ref)))


def _emit_audit(event_type: str, payload: dict) -> None:
    from . import audit_log

    audit_log.append(
        event_type=event_type,
        actor="settlement_layer",
        context_kind="insurance_payout",
        payload=payload,
    )


# ── Persistence (write-behind, mirrors store.py) ──────────────────────────────

async def load_from_db() -> None:
    """Hydrate insurance state from Postgres on startup. No-op without a DB."""
    if db.session_factory is None:
        return
    from sqlalchemy import select

    from ..models import AgentRiskRecord
    from ..models import InsurancePayoutRecord as PayoutRow
    from ..models import InsurancePremiumRecord as PremiumRow

    try:
        async with db.session_factory() as session:
            for row in (await session.execute(select(AgentRiskRecord))).scalars().all():
                _agent_risk[row.agent_address] = AgentRisk(
                    alpha=row.alpha, beta=row.beta, n0=row.n0, a0=row.a0, b0=row.b0, last_ts=row.last_ts
                )
                _bands[row.agent_address] = row.score_band
            for row in (await session.execute(select(PremiumRow))).scalars().all():
                _premiums.append(InsurancePremiumRecord(
                    id=row.id, job_id=row.job_id, agent_address=row.agent_address,
                    premium_amount=row.premium_amount, currency=row.currency, tx_hash=row.tx_hash,
                    explorer_url=row.explorer_url, score_band=row.score_band, created_at=row.created_at,
                ))
                _pool["premiums"] += Decimal(row.premium_amount)
            for row in (await session.execute(select(PayoutRow))).scalars().all():
                _payouts.append(InsurancePayoutRecord(
                    id=row.id, job_id=row.job_id, merchant=row.merchant,
                    collateral_slashed=row.collateral_slashed, pool_drawn=row.pool_drawn,
                    total_paid=row.total_paid, currency=row.currency, slash_tx_hash=row.slash_tx_hash,
                    pool_draw_tx_hash=row.pool_draw_tx_hash, explorer_url=row.explorer_url,
                    reputation_mpt_protected=row.reputation_mpt_protected, created_at=row.created_at,
                ))
                _pool["payouts"] += Decimal(row.pool_drawn)
    except Exception as exc:
        log.warning("Failed to load insurance state from DB: %s", exc)


async def _persist_premium(rec: InsurancePremiumRecord) -> None:
    if db.session_factory is None:
        return
    from ..models import InsurancePremiumRecord as PremiumRow

    try:
        async with db.session_factory() as session:
            await session.merge(PremiumRow(
                id=rec.id, job_id=rec.job_id, agent_address=rec.agent_address,
                premium_amount=rec.premium_amount, currency=rec.currency, tx_hash=rec.tx_hash,
                explorer_url=rec.explorer_url, score_band=rec.score_band, created_at=rec.created_at,
            ))
            await session.commit()
    except Exception as exc:
        log.warning("Failed to persist premium %s: %s", rec.id, exc)


async def _persist_payout(rec: InsurancePayoutRecord) -> None:
    if db.session_factory is None:
        return
    from ..models import InsurancePayoutRecord as PayoutRow

    try:
        async with db.session_factory() as session:
            await session.merge(PayoutRow(
                id=rec.id, job_id=rec.job_id, merchant=rec.merchant,
                collateral_slashed=rec.collateral_slashed, pool_drawn=rec.pool_drawn,
                total_paid=rec.total_paid, currency=rec.currency, slash_tx_hash=rec.slash_tx_hash,
                pool_draw_tx_hash=rec.pool_draw_tx_hash, explorer_url=rec.explorer_url,
                reputation_mpt_protected=rec.reputation_mpt_protected, created_at=rec.created_at,
            ))
            await session.commit()
    except Exception as exc:
        log.warning("Failed to persist payout %s: %s", rec.id, exc)


async def _persist_risk(agent_address: str, r: AgentRisk, score_band: str | None) -> None:
    if db.session_factory is None:
        return
    from ..models import AgentRiskRecord

    try:
        async with db.session_factory() as session:
            await session.merge(AgentRiskRecord(
                agent_address=agent_address, score_band=score_band,
                alpha=r.alpha, beta=r.beta, n0=r.n0, a0=r.a0, b0=r.b0, last_ts=r.last_ts,
            ))
            await session.commit()
    except Exception as exc:
        log.warning("Failed to persist agent risk %s: %s", agent_address, exc)


def _schedule(coro) -> None:
    """Fire-and-forget DB persist if a loop is running; close cleanly otherwise."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(coro)
            return
    except RuntimeError:
        pass
    try:
        coro.close()
    except Exception:
        pass


# ── Errors ────────────────────────────────────────────────────────────────────

class InsuranceError(Exception):
    pass


class InsuranceDisabled(InsuranceError):
    pass


class InsuranceConfigError(InsuranceError):
    pass


class CoverUnavailable(InsuranceError):
    """The re-quote did not return an OFFER (REVIEW/DECLINE)."""

    def __init__(self, decision: str, reason: str):
        super().__init__(f"{decision}: {reason}")
        self.decision = decision
        self.reason = reason


class PayoutRefused(InsuranceError):
    pass


class GuardrailRefused(InsuranceError):
    """A per-party compliance guardrail hard-blocked the action."""

    def __init__(self, guardrail: str, reason: str, trail: list[GuardrailResult]):
        super().__init__(f"{guardrail}: {reason}")
        self.guardrail = guardrail
        self.reason = reason
        self.trail = trail
