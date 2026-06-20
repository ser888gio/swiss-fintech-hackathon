"""Business-defined payment agent endpoints.

CRUD for Agent entities + per-agent goals + run + dashboard stats.
Each agent has its own policy scope (caps, allowlists, blocklists) that the
orchestrator enforces deterministically — the LLM never touches these values.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, Response

from ..agents import orchestrator, treasury_agent
from ..config import get_settings
from ..policy.scope import GLOBAL_AUTO_SETTLE_CEILING_USD, AgentScope, evaluate_scope
from ..schemas import (
    Agent,
    AgentCreate,
    AgentDashboardStats,
    AgentStatus,
    AgentUpdate,
    ServicePaymentRecord,
    TreasuryAgentRun,
    TreasuryGoal,
    TreasuryGoalCreate,
)
from .. import store

router = APIRouter(prefix="/agents", tags=["agents"])

# In-memory agent registry (write-through to Postgres when DB is available).
_agents: dict[str, Agent] = {}


def has_registered_agent(agent_id: str) -> bool:
    """Return whether Demo Lab may bind a scenario to this agent."""
    return agent_id in _agents


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


MAERSK_SUBAGENTS = (
    "repair-bot", "tax-bot", "port-bot", "fuel-bot", "insurance-bot"
)


@router.get("/service-payments/history", response_model=list[ServicePaymentRecord])
async def service_payment_history(agent_id: str | None = None) -> list[ServicePaymentRecord]:
    return store.list_service_payments(agent_id)


@router.post("/seed-maersk", response_model=list[Agent])
async def seed_maersk(request: Request) -> list[Agent]:
    """Idempotently seed one controller and five shared-wallet role agents."""
    settings = get_settings()
    base_url = str(request.base_url).rstrip("/")
    host = request.url.netloc
    definitions = (
        ("repair-bot", "Repairs Agent", "repairs", "5", "20", "3", "repair-yard", "2.000000"),
        ("tax-bot", "Taxes Agent", "taxes", "10", "30", "6", "customs", "5.000000"),
        ("port-bot", "Port Fees Agent", "port_fees", "4", "15", "3", "port-authority", "2.500000"),
        ("fuel-bot", "Fuel Agent", "fuel", "5", "25", "3", "bunker-fuel", "2.750000"),
        ("insurance-bot", "Marine Insurance Agent", "insurance", "6", "25", "4", "marine-insurance", "3.000000"),
    )
    if "maersk-controller" not in _agents:
        await create_agent(AgentCreate(
            id="maersk-controller",
            name="Maersk Fleet Controller",
            description="Aggregation handle only; it never initiates payments.",
            max_single_payment="0.000001",
            max_daily_spend="0.000001",
            requires_approval_above="0",
            allowed_categories=[],
            allowed_assets=[settings.token_currency],
            allowed_network=settings.xrpl_network,
            allowed_hosts=[],
            require_known_merchant=True,
        ))
    for agent_id, name, category, max_tx, max_day, approval, slug, amount in definitions:
        if agent_id not in _agents:
            await create_agent(AgentCreate(
                id=agent_id,
                name=name,
                description=f"Maersk autonomous {category} spend specialist.",
                max_single_payment=max_tx,
                max_daily_spend=max_day,
                requires_approval_above=approval,
                allowed_categories=[category],
                allowed_assets=[settings.token_currency],
                allowed_network=settings.xrpl_network,
                allowed_hosts=[host],
                require_known_merchant=True,
            ))
        if not treasury_agent.list_agent_goals(agent_id):
            url = f"{base_url}/merchants/{slug}"
            goal = treasury_agent.goal_from_create(TreasuryGoalCreate(
                name=f"Settle {category.replace('_', ' ')} invoice",
                beneficiary_name=slug.replace("-", " ").title(),
                beneficiary_address="rMERCHANT_RESOLVED_FROM_402",
                beneficiary_country="CH",
                amount=float(amount),
                currency=settings.token_currency,
                reference=f"MAERSK-{agent_id.upper()}",
                purpose=category,
                category=category,
                service_url=url,
                service_type=category,
                trigger_interval_hours=24,
            )).model_copy(update={"agent_id": agent_id})
            treasury_agent.add_agent_goal(agent_id, goal)
            if agent_id == "repair-bot":
                blocked = treasury_agent.goal_from_create(TreasuryGoalCreate(
                    name="Demonstrate approval-threshold block",
                    beneficiary_name="Repair Yard",
                    beneficiary_address="rMERCHANT_RESOLVED_FROM_402",
                    beneficiary_country="CH",
                    amount=4,
                    currency=settings.token_currency,
                    reference="MAERSK-REPAIR-BLOCK",
                    purpose=category,
                    category=category,
                    service_url=f"{url}?price=4.000000",
                    service_type=category,
                    trigger_interval_hours=24,
                )).model_copy(update={"agent_id": agent_id})
                treasury_agent.add_agent_goal(agent_id, blocked)
    # Keep the hardware-veto story on the existing direct-payment path. Only
    # seed it when a real demo counterparty is configured; never invent a payee.
    direct_payee = getattr(settings, "x402_demo_pay_to", "")
    if direct_payee and not any(
        goal.reference == "MAERSK-FIREFLY-VETO" for goal in treasury_agent.list_goals()
    ):
        treasury_agent.add_goal(treasury_agent.goal_from_create(TreasuryGoalCreate(
            name="Institutional transfer — Firefly veto demo",
            beneficiary_name="Maersk Institutional Counterparty",
            beneficiary_address=direct_payee,
            beneficiary_country="CH",
            amount=15_000,
            currency=settings.token_currency,
            reference="MAERSK-FIREFLY-VETO",
            purpose="institutional_transfer",
            trigger_interval_hours=8760,
        )))
    return [_agents["maersk-controller"], *[_agents[a] for a in MAERSK_SUBAGENTS]]


@router.post("/controller/run", response_model=TreasuryAgentRun)
async def run_controller(force: bool = False, simulate: bool = False) -> TreasuryAgentRun:
    settings = get_settings()
    if not settings.agent_enabled:
        raise HTTPException(status_code=403, detail="autonomous agent is disabled")
    started = datetime.now(timezone.utc)
    # Judge-demo runs must be repeatable. Reset only the seeded fleet goals'
    # cadence timestamps; all policy, credential, reservation, and settlement
    # checks still execute normally below.
    if force:
        for agent_id in MAERSK_SUBAGENTS:
            for goal in treasury_agent.list_agent_goals(agent_id):
                treasury_agent.add_agent_goal(
                    agent_id, goal.model_copy(update={"last_triggered_at": None})
                )
    if simulate:
        evaluated = 0
        eligible: list[str] = []
        skipped: list[str] = []
        trail: list[str] = []
        for agent_id in MAERSK_SUBAGENTS:
            agent = _agents.get(agent_id)
            if not agent or agent.status != AgentStatus.active:
                continue
            scope = _build_scope(agent)
            for goal in treasury_agent.list_agent_goals(agent_id):
                evaluated += 1
                host = urlparse(goal.service_url).netloc if goal.service_url else None
                decision = evaluate_scope(
                    Decimal(str(goal.amount)), scope, Decimal("0"),
                    service_host=host,
                    service_type=goal.service_type,
                    asset=goal.currency,
                    network=agent.allowed_network,
                    category=goal.category or goal.purpose,
                    payee_is_known_merchant=True,
                )
                if decision.allowed:
                    eligible.append(f"SIM-{agent_id}-{goal.id[:8]}")
                    trail.append(
                        f"[{agent_id}] {goal.name}: ELIGIBLE — scope, asset, host, "
                        f"per-transaction and daily limits passed ({goal.amount:g} {goal.currency})."
                    )
                else:
                    skipped.append(goal.id)
                    outcome = "ESCALATE" if decision.requires_approval else "BLOCK"
                    trail.append(
                        f"[{agent_id}] {goal.name}: {outcome} — "
                        f"{decision.rule_fired}: {'; '.join(decision.reasons)}"
                    )
        now = datetime.now(timezone.utc)
        return TreasuryAgentRun(
            id=str(uuid.uuid4()), started_at=started, completed_at=now,
            goals_evaluated=evaluated, goals_triggered=len(eligible),
            payments_initiated=eligible, payments_skipped=skipped,
            trigger_log=trail,
            narration=(
                f"Simulation evaluated {evaluated} due service goals through the deterministic "
                f"agent scope policy. {len(eligible)} are eligible for autonomous x402 settlement; "
                f"{len(skipped)} require escalation or are blocked. No funds moved in this judge simulation."
            ),
            status="simulated", agent_id="maersk-controller",
        )
    runs: list[TreasuryAgentRun] = []
    for agent_id in MAERSK_SUBAGENTS:
        agent = _agents.get(agent_id)
        if agent and agent.status == AgentStatus.active:
            runs.append(await treasury_agent.run_for_agent(agent_id, _build_scope(agent)))
    payments = [payment for run in runs for payment in run.payments_initiated]
    skipped = [goal for run in runs for goal in run.payments_skipped]
    trail = [f"[{run.agent_id}] {line}" for run in runs for line in run.trigger_log]
    goals = [goal for agent_id in MAERSK_SUBAGENTS for goal in treasury_agent.list_agent_goals(agent_id)]
    narration = await treasury_agent._narrate(goals, trail, payments, settings)
    aggregate = TreasuryAgentRun(
        id=str(uuid.uuid4()),
        started_at=started,
        completed_at=datetime.now(timezone.utc),
        goals_evaluated=sum(run.goals_evaluated for run in runs),
        goals_triggered=sum(run.goals_triggered for run in runs),
        payments_initiated=payments,
        payments_skipped=skipped,
        trigger_log=trail,
        narration=narration,
        status="completed",
        agent_id="maersk-controller",
    )
    treasury_agent._agent_runs.setdefault("maersk-controller", []).append(aggregate)
    treasury_agent._schedule(treasury_agent._persist_run(aggregate))
    return aggregate


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
    service_payments = store.list_service_payments(agent_id)
    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)

    payments_today = [p for p in all_payments if p.created_at >= since_24h]
    amount_today = sum(
        Decimal(str(p.intent.amount)) for p in payments_today
        if p.status.value not in ("blocked", "failed")
    )
    service_today = [p for p in service_payments if p.created_at >= since_24h]
    amount_today += sum(
        (Decimal(p.amount) for p in service_today if p.status == "settled"),
        Decimal("0"),
    )
    pending = [p for p in all_payments if p.status.value == "pending_approval"]
    blocked = [p for p in all_payments if p.status.value == "blocked"]
    escalated = [p for p in all_payments if p.status.value in ("pending_approval", "released")]

    last_run = runs[0] if runs else None
    return AgentDashboardStats(
        agent_id=agent_id,
        payments_today=len(payments_today) + len(service_today),
        amount_spent_today=str(amount_today),
        pending_approvals=len(pending),
        last_run_at=last_run.started_at if last_run else None,
        last_run_status=last_run.status if last_run else None,
        total_payments=len(all_payments) + len(service_payments),
        total_blocked=len(blocked) + len([p for p in service_payments if p.status == "blocked"]),
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
        allowed_network=row.allowed_network or "xrpl:1",
        allowed_addresses=row.allowed_addresses,
        blocked_addresses=row.blocked_addresses or [],
        allowed_hosts=row.allowed_hosts,
        blocked_hosts=row.blocked_hosts or [],
        require_known_merchant=row.require_known_merchant or False,
        policy_revision=row.policy_revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
