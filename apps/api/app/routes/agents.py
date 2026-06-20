"""Business-defined payment agent endpoints.

CRUD for Agent entities + per-agent goals + run + dashboard stats.
Each agent has its own policy scope (caps, allowlists, blocklists) that the
orchestrator enforces deterministically — the LLM never touches these values.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, HTTPException, Response

from ..agents import orchestrator, treasury_agent
from ..config import get_settings
from ..policy.scope import GLOBAL_AUTO_SETTLE_CEILING_USD, AgentScope
from ..schemas import (
    Agent,
    AgentCreate,
    AgentDashboardStats,
    AgentStatus,
    AgentUpdate,
    TreasuryAgentRun,
    TreasuryGoal,
    TreasuryGoalCreate,
)
from .. import store

router = APIRouter(prefix="/agents", tags=["agents"])

# In-memory agent registry (write-through to Postgres when DB is available).
_agents: dict[str, Agent] = {}


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.post("", response_model=Agent, status_code=201)
async def create_agent(req: AgentCreate) -> Agent:
    if req.id in _agents:
        raise HTTPException(status_code=409, detail=f"agent '{req.id}' already exists")
    _validate_money_fields(req.max_single_payment, req.max_daily_spend, req.requires_approval_above)
    now = datetime.now(timezone.utc)
    agent = Agent(
        **req.model_dump(by_alias=False),
        status=AgentStatus.active,
        policy_revision=1,
        created_at=now,
        updated_at=now,
    )
    _agents[agent.id] = agent
    _schedule_persist(agent)
    return agent


@router.get("", response_model=list[Agent])
async def list_agents() -> list[Agent]:
    return sorted(_agents.values(), key=lambda a: a.created_at, reverse=True)


@router.get("/{agent_id}", response_model=Agent)
async def get_agent(agent_id: str) -> Agent:
    return _get_or_404(agent_id)


@router.put("/{agent_id}", response_model=Agent)
async def update_agent(agent_id: str, req: AgentUpdate) -> Agent:
    agent = _get_or_404(agent_id)
    patch = req.model_dump(exclude_none=True, by_alias=False)
    if any(k in patch for k in ("max_single_payment", "max_daily_spend", "requires_approval_above")):
        new_single = patch.get("max_single_payment", agent.max_single_payment)
        new_daily = patch.get("max_daily_spend", agent.max_daily_spend)
        new_above = patch.get("requires_approval_above", agent.requires_approval_above)
        _validate_money_fields(new_single, new_daily, new_above)
    patch["policy_revision"] = agent.policy_revision + 1
    patch["updated_at"] = datetime.now(timezone.utc)
    updated = agent.model_copy(update=patch)
    _agents[agent_id] = updated
    _schedule_persist(updated)
    return updated


@router.delete("/{agent_id}", status_code=204, response_class=Response)
async def delete_agent(agent_id: str) -> Response:
    _get_or_404(agent_id)
    _agents.pop(agent_id)
    # Goals are dropped with the agent; runs kept for audit.
    return Response(status_code=204)


# ── Per-agent goals ───────────────────────────────────────────────────────────

@router.post("/{agent_id}/goals", response_model=TreasuryGoal, status_code=201)
async def create_agent_goal(agent_id: str, req: TreasuryGoalCreate) -> TreasuryGoal:
    _get_or_404(agent_id)
    goal = treasury_agent.goal_from_create(req)
    goal = goal.model_copy(update={"agent_id": agent_id})
    return treasury_agent.add_agent_goal(agent_id, goal)


@router.get("/{agent_id}/goals", response_model=list[TreasuryGoal])
async def list_agent_goals(agent_id: str) -> list[TreasuryGoal]:
    _get_or_404(agent_id)
    return treasury_agent.list_agent_goals(agent_id)


@router.delete("/{agent_id}/goals/{goal_id}", status_code=204, response_class=Response)
async def delete_agent_goal(agent_id: str, goal_id: str) -> Response:
    _get_or_404(agent_id)
    if not treasury_agent.remove_agent_goal(agent_id, goal_id):
        raise HTTPException(status_code=404, detail="goal not found")
    return Response(status_code=204)


# ── Run ───────────────────────────────────────────────────────────────────────

@router.post("/{agent_id}/run", response_model=TreasuryAgentRun)
async def run_agent(agent_id: str) -> TreasuryAgentRun:
    agent = _get_or_404(agent_id)
    if agent.status == AgentStatus.paused:
        raise HTTPException(status_code=403, detail=f"agent '{agent_id}' is paused; unpause before running")
    if not get_settings().agent_enabled:
        raise HTTPException(status_code=403, detail="autonomous agent is disabled (AGENT_ENABLED=false)")
    scope = _build_scope(agent)
    try:
        return await treasury_agent.run_for_agent(agent_id, scope)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/{agent_id}/runs", response_model=list[TreasuryAgentRun])
async def list_agent_runs(agent_id: str) -> list[TreasuryAgentRun]:
    _get_or_404(agent_id)
    return treasury_agent.list_agent_runs(agent_id)


# ── Dashboard stats ───────────────────────────────────────────────────────────

@router.get("/{agent_id}/stats", response_model=AgentDashboardStats)
async def get_agent_stats(agent_id: str) -> AgentDashboardStats:
    agent = _get_or_404(agent_id)
    runs = treasury_agent.list_agent_runs(agent_id)

    # Collect all payment IDs ever initiated by this agent (from run history).
    all_payment_ids: set[str] = set()
    for r in runs:
        all_payment_ids.update(r.payments_initiated)

    # Pull payment objects from the in-memory store.
    all_payments = [p for p in store.list_payments() if p.agent_id == agent_id]
    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)

    payments_today = [p for p in all_payments if p.created_at >= since_24h]
    amount_today = sum(
        Decimal(str(p.intent.amount)) for p in payments_today
        if p.status.value not in ("blocked", "failed")
    )
    pending = [p for p in all_payments if p.status.value == "pending_approval"]
    blocked = [p for p in all_payments if p.status.value == "blocked"]
    escalated = [p for p in all_payments if p.status.value in ("pending_approval", "released")]

    last_run = runs[0] if runs else None
    return AgentDashboardStats(
        agent_id=agent_id,
        payments_today=len(payments_today),
        amount_spent_today=str(amount_today),
        pending_approvals=len(pending),
        last_run_at=last_run.started_at if last_run else None,
        last_run_status=last_run.status if last_run else None,
        total_payments=len(all_payments),
        total_blocked=len(blocked),
        total_escalated=len(escalated),
    )


# ── Startup hydration from DB ─────────────────────────────────────────────────

async def load_agents_from_db() -> None:
    """Hydrate _agents from Postgres on startup."""
    from .. import db
    from ..models import AgentRecord
    from sqlalchemy import select
    if db.session_factory is None:
        return
    try:
        async with db.session_factory() as session:
            rows = (await session.execute(select(AgentRecord))).scalars().all()
            for row in rows:
                if row.id not in _agents:
                    _agents[row.id] = _row_to_agent(row)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Failed to load agents from DB: %s", exc)


# ── Private helpers ───────────────────────────────────────────────────────────

def _get_or_404(agent_id: str) -> Agent:
    agent = _agents.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent '{agent_id}' not found")
    return agent


def _validate_money_fields(
    max_single: str,
    max_daily: str,
    requires_above: str,
) -> None:
    try:
        s = Decimal(max_single)
        d = Decimal(max_daily)
        a = Decimal(requires_above)
    except InvalidOperation:
        raise HTTPException(status_code=422, detail="money fields must be valid decimal strings")
    if s <= 0 or d <= 0 or a < 0:
        raise HTTPException(status_code=422, detail="money caps must be positive")
    if a > s:
        raise HTTPException(
            status_code=422,
            detail=f"requires_approval_above ({a}) must be ≤ max_single_payment ({s})",
        )
    ceiling = GLOBAL_AUTO_SETTLE_CEILING_USD
    if a > ceiling:
        raise HTTPException(
            status_code=422,
            detail=f"requires_approval_above ({a}) may not exceed global ceiling ({ceiling})",
        )


def _build_scope(agent: Agent) -> AgentScope:
    """Convert an Agent config row into an AgentScope for evaluate_scope()."""
    return AgentScope(
        max_per_transaction=Decimal(agent.max_single_payment),
        max_per_day=Decimal(agent.max_daily_spend),
        requires_approval_above=Decimal(agent.requires_approval_above),
        allowed_addresses=agent.allowed_addresses,
        blocked_addresses=agent.blocked_addresses or [],
        allowed_service_hosts=agent.allowed_hosts,
        blocked_service_hosts=agent.blocked_hosts or [],
        allowed_categories=agent.allowed_categories,
        allowed_assets=agent.allowed_assets,
        allowed_network=agent.allowed_network or None,
        require_known_merchant=agent.require_known_merchant,
    )


def _schedule_persist(agent: Agent) -> None:
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_persist_agent(agent))
    except RuntimeError:
        pass


async def _persist_agent(agent: Agent) -> None:
    from .. import db
    from ..models import AgentRecord
    if db.session_factory is None:
        return
    try:
        async with db.session_factory() as session:
            row = AgentRecord(
                id=agent.id,
                name=agent.name,
                description=agent.description,
                status=agent.status.value,
                currency=agent.currency,
                max_single_payment=agent.max_single_payment,
                max_daily_spend=agent.max_daily_spend,
                requires_approval_above=agent.requires_approval_above,
                allowed_categories=agent.allowed_categories,
                allowed_assets=agent.allowed_assets,
                allowed_network=agent.allowed_network,
                allowed_addresses=agent.allowed_addresses,
                blocked_addresses=agent.blocked_addresses,
                allowed_hosts=agent.allowed_hosts,
                blocked_hosts=agent.blocked_hosts,
                require_known_merchant=agent.require_known_merchant,
                policy_revision=agent.policy_revision,
                created_at=agent.created_at,
                updated_at=agent.updated_at,
            )
            await session.merge(row)
            await session.commit()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Failed to persist agent %s: %s", agent.id, exc)


def _row_to_agent(row) -> Agent:
    return Agent(
        id=row.id,
        name=row.name,
        description=getattr(row, "description", None),
        status=AgentStatus(row.status),
        currency=row.currency,
        max_single_payment=row.max_single_payment,
        max_daily_spend=row.max_daily_spend,
        requires_approval_above=row.requires_approval_above,
        allowed_categories=row.allowed_categories,
        allowed_assets=row.allowed_assets or ["RLUSD"],
        allowed_network=row.allowed_network or "XRPL",
        allowed_addresses=row.allowed_addresses,
        blocked_addresses=row.blocked_addresses or [],
        allowed_hosts=row.allowed_hosts,
        blocked_hosts=row.blocked_hosts or [],
        require_known_merchant=row.require_known_merchant or False,
        policy_revision=row.policy_revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
