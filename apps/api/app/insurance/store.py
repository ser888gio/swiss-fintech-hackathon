from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select

from .. import db
from ..models import (
    AgentRiskRecord as AgentRiskRecordDB,
    InsurancePayoutRecord as InsurancePayoutRecordDB,
    InsurancePremiumRecord as InsurancePremiumRecordDB,
)
from ..schemas import AgentRiskState, InsurancePayoutRecord, InsurancePremiumRecord

log = logging.getLogger(__name__)

_agent_risks: dict[str, AgentRiskState] = {}
_premiums: dict[str, InsurancePremiumRecord] = {}
_payouts: dict[str, InsurancePayoutRecord] = {}


def get_agent_risk(address: str) -> AgentRiskState | None:
    return _agent_risks.get(address)


def save_agent_risk(state: AgentRiskState) -> AgentRiskState:
    _agent_risks[state.agent_address] = state
    _schedule(_persist_agent_risk(state))
    return state


def list_agent_risks() -> list[AgentRiskState]:
    return sorted(_agent_risks.values(), key=lambda item: item.updated_at, reverse=True)


def save_premium(record: InsurancePremiumRecord) -> InsurancePremiumRecord:
    _premiums[record.id] = record
    _schedule(_persist_premium(record))
    return record


def list_premiums() -> list[InsurancePremiumRecord]:
    return sorted(_premiums.values(), key=lambda item: item.created_at, reverse=True)


def save_payout(record: InsurancePayoutRecord) -> InsurancePayoutRecord:
    _payouts[record.id] = record
    _schedule(_persist_payout(record))
    return record


def list_payouts() -> list[InsurancePayoutRecord]:
    return sorted(_payouts.values(), key=lambda item: item.created_at, reverse=True)


async def load_from_db() -> None:
    if db.session_factory is None:
        return
    try:
        async with db.session_factory() as session:
            await _load_agent_risks(session)
            await _load_premiums(session)
            await _load_payouts(session)
    except Exception as exc:
        log.warning("Failed to load insurance state from DB: %s", exc)


async def _load_agent_risks(session) -> None:
    rows = (await session.execute(select(AgentRiskRecordDB))).scalars().all()
    for row in rows:
        _agent_risks[row.agent_address] = AgentRiskState(
            agent_address=row.agent_address,
            score_band=row.score_band,
            alpha=row.alpha,
            beta=row.beta,
            pd=row.pd,
            credibility=row.credibility,
            updated_at=row.updated_at,
        )


async def _load_premiums(session) -> None:
    rows = (await session.execute(select(InsurancePremiumRecordDB))).scalars().all()
    for row in rows:
        _premiums[row.id] = InsurancePremiumRecord(
            id=row.id,
            job_id=row.job_id,
            agent_address=row.agent_address,
            premium_amount=row.premium_amount,
            currency=row.currency,
            tx_hash=row.tx_hash,
            explorer_url=row.explorer_url,
            score_band=row.score_band,
            created_at=row.created_at,
        )


async def _load_payouts(session) -> None:
    rows = (await session.execute(select(InsurancePayoutRecordDB))).scalars().all()
    for row in rows:
        _payouts[row.id] = InsurancePayoutRecord(
            id=row.id,
            job_id=row.job_id,
            merchant=row.merchant,
            collateral_slashed=row.collateral_slashed,
            pool_drawn=row.pool_drawn,
            total_paid=row.total_paid,
            currency=row.currency,
            slash_tx_hash=row.slash_tx_hash,
            pool_draw_tx_hash=row.pool_draw_tx_hash,
            reputation_mpt_protected=row.reputation_mpt_protected,
            created_at=row.created_at,
        )


async def _persist_agent_risk(state: AgentRiskState) -> None:
    if db.session_factory is None:
        return
    try:
        async with db.session_factory() as session:
            await session.merge(
                AgentRiskRecordDB(
                    agent_address=state.agent_address,
                    score_band=state.score_band,
                    alpha=state.alpha,
                    beta=state.beta,
                    pd=state.pd,
                    credibility=state.credibility,
                    updated_at=state.updated_at,
                )
            )
            await session.commit()
    except Exception as exc:
        log.warning("Failed to persist agent risk %s: %s", state.agent_address, exc)


async def _persist_premium(record: InsurancePremiumRecord) -> None:
    if db.session_factory is None:
        return
    try:
        async with db.session_factory() as session:
            await session.merge(
                InsurancePremiumRecordDB(
                    id=record.id,
                    job_id=record.job_id,
                    agent_address=record.agent_address,
                    premium_amount=record.premium_amount,
                    currency=record.currency,
                    tx_hash=record.tx_hash,
                    explorer_url=record.explorer_url,
                    score_band=record.score_band,
                    created_at=record.created_at,
                )
            )
            await session.commit()
    except Exception as exc:
        log.warning("Failed to persist insurance premium %s: %s", record.id, exc)


async def _persist_payout(record: InsurancePayoutRecord) -> None:
    if db.session_factory is None:
        return
    try:
        async with db.session_factory() as session:
            await session.merge(
                InsurancePayoutRecordDB(
                    id=record.id,
                    job_id=record.job_id,
                    merchant=record.merchant,
                    collateral_slashed=record.collateral_slashed,
                    pool_drawn=record.pool_drawn,
                    total_paid=record.total_paid,
                    currency=record.currency,
                    slash_tx_hash=record.slash_tx_hash,
                    pool_draw_tx_hash=record.pool_draw_tx_hash,
                    reputation_mpt_protected=record.reputation_mpt_protected,
                    created_at=record.created_at,
                )
            )
            await session.commit()
    except Exception as exc:
        log.warning("Failed to persist insurance payout %s: %s", record.id, exc)


def _schedule(coro) -> None:
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

