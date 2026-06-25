"""Autonomous Treasury Agent.

Evaluates a configurable set of payment goals and initiates those whose
deterministic trigger conditions are met. The decision logic is pure Python —
time elapsed since last trigger and an amount cap — never the LLM. The
ONLY actuator is `orchestrator.process_payment`, which runs the full
compliance screen, policy gate, and Firefly hardware veto for large amounts.

The LLM (when an OPENAI_API_KEY is configured) writes one paragraph narrating
what was evaluated and initiated each cycle. It reports facts — it does not
decide whether to pay.

Invariant enforced here:
  evaluate_goal() is a pure function with no I/O. The LLM is called after all
  decisions are made and only writes the narration. It never touches policy or
  execution.
"""

from __future__ import annotations

import uuid
import asyncio
from datetime import datetime, timezone

from ..config import get_settings
from ..policy.scope import AgentScope
from ..schemas import (
    PaymentIntent,
    PaymentStatus,
    TreasuryAgentRun,
    TreasuryGoal,
    TreasuryGoalCreate,
)
from ..tools import mptoken as mptoken_tool
from ..tools import vault as vault_tool
from . import orchestrator

# In-memory goal registry (survives the process lifetime; loaded from config or
# populated via the /treasury/goals API).
_goals: dict[str, TreasuryGoal] = {}
_runs: list[TreasuryAgentRun] = []

# Per-business-agent goal registry: agent_id → {goal_id: TreasuryGoal}
_agent_goals: dict[str, dict[str, TreasuryGoal]] = {}
# Per-agent run history: agent_id → [TreasuryAgentRun]
_agent_runs: dict[str, list[TreasuryAgentRun]] = {}
# Per-agent run lock: prevents concurrent run(agent_id) for the same agent
_agent_run_lock: dict[str, bool] = {}


# ── Goal registry (global / legacy) ──────────────────────────────────────────


def add_goal(goal: TreasuryGoal) -> TreasuryGoal:
    _goals[goal.id] = goal
    _schedule(_persist_goal(goal))
    return goal


def remove_goal(goal_id: str) -> bool:
    removed = _goals.pop(goal_id, None) is not None
    if removed:
        _schedule(_delete_goal(goal_id))
    return removed


def get_goal(goal_id: str) -> TreasuryGoal | None:
    return _goals.get(goal_id)


def list_goals() -> list[TreasuryGoal]:
    return list(_goals.values())


def list_runs() -> list[TreasuryAgentRun]:
    return list(reversed(_runs))


# ── Per-agent goal registry ───────────────────────────────────────────────────


def add_agent_goal(agent_id: str, goal: TreasuryGoal) -> TreasuryGoal:
    _agent_goals.setdefault(agent_id, {})[goal.id] = goal
    _schedule(_persist_goal(goal.model_copy(update={"agent_id": agent_id})))
    return goal


def remove_agent_goal(agent_id: str, goal_id: str) -> bool:
    removed = _agent_goals.get(agent_id, {}).pop(goal_id, None) is not None
    if removed:
        _schedule(_delete_goal(goal_id))
    return removed


def get_agent_goal(agent_id: str, goal_id: str) -> TreasuryGoal | None:
    return _agent_goals.get(agent_id, {}).get(goal_id)


def list_agent_goals(agent_id: str) -> list[TreasuryGoal]:
    return list(_agent_goals.get(agent_id, {}).values())


def list_agent_runs(agent_id: str) -> list[TreasuryAgentRun]:
    return list(reversed(_agent_runs.get(agent_id, [])))


def goal_from_create(request: TreasuryGoalCreate) -> TreasuryGoal:
    return TreasuryGoal(
        id=str(uuid.uuid4()),
        **request.model_dump(by_alias=False),
    )


# ── Core deterministic trigger ────────────────────────────────────────────────


def evaluate_goal(
    goal: TreasuryGoal,
    now: datetime,
    agent_max_amount_usd: float,
) -> tuple[bool, str]:
    """Decide whether a goal should fire RIGHT NOW. Pure function, no I/O.

    Returns (should_fire, reason). All decisions are deterministic code —
    never the LLM. The LLM narrates these reasons after the fact.
    """
    if not goal.enabled:
        return False, "goal disabled"

    if goal.amount > agent_max_amount_usd:
        return False, (
            f"amount {goal.amount:,.2f} {goal.currency} exceeds agent cap "
            f"{agent_max_amount_usd:,.0f} USD — use the payments API for large transfers"
        )

    if goal.last_triggered_at is None:
        return True, "never triggered before — firing on first cycle"

    elapsed_hours = (now - goal.last_triggered_at).total_seconds() / 3600
    if elapsed_hours >= goal.trigger_interval_hours:
        return True, (
            f"interval {goal.trigger_interval_hours:g}h elapsed "
            f"({elapsed_hours:.1f}h since last trigger at "
            f"{goal.last_triggered_at.strftime('%Y-%m-%dT%H:%M')}Z)"
        )

    remaining = goal.trigger_interval_hours - elapsed_hours
    return False, (
        f"interval {goal.trigger_interval_hours:g}h not yet elapsed "
        f"({remaining:.1f}h remaining)"
    )


# ── Agent run ─────────────────────────────────────────────────────────────────


async def run(goals: list[TreasuryGoal] | None = None) -> TreasuryAgentRun:
    """Run one evaluation cycle over all active goals (or an explicit list).

    For each goal whose trigger condition is met, fires
    `orchestrator.process_payment` — the only actuator. Updates
    `last_triggered_at` on fired goals. Appends a run record and returns it.
    """
    settings = get_settings()
    now = _now()
    run_id = str(uuid.uuid4())
    active_goals = goals if goals is not None else list(_goals.values())

    payments_initiated: list[str] = []
    payments_skipped: list[str] = []
    trigger_log: list[str] = []

    for goal in active_goals:
        should_fire, reason = evaluate_goal(goal, now, settings.agent_max_amount_usd)
        trigger_log.append(f"[{goal.name}] {reason}.")

        if not should_fire:
            payments_skipped.append(goal.id)
            continue

        # Deterministic actuator only — orchestrator enforces policy + Firefly veto.
        intent = _build_intent(goal, settings)
        try:
            payment = await orchestrator.process_payment(intent)
        except Exception as exc:
            trigger_log.append(f"  ✗ payment initiation failed: {exc}")
            payments_skipped.append(goal.id)
            continue

        payments_initiated.append(payment.id)
        trigger_log.append(
            f"  → payment {payment.id[:8]}… status={payment.status.value}"
            + (
                f", rule={payment.policy_decision.rule_fired}"
                if payment.policy_decision and payment.policy_decision.rule_fired
                else ""
            )
        )
        # Mint compliance attestation for every auto-settled payment.
        if settings.mpt_enabled and payment.status == PaymentStatus.settled:
            await _mint_compliance_attestation(payment, trigger_log, settings)
        # Update last_triggered_at on the stored goal.
        add_goal(goal.model_copy(update={"last_triggered_at": now}))

    # Deterministic vault sweep: deposit excess above threshold, recall when low.
    # Only runs when vault_enabled=True; never the LLM's decision.
    await _vault_sweep(trigger_log, settings)

    narration = await _narrate(active_goals, trigger_log, payments_initiated, settings)

    agent_run = TreasuryAgentRun(
        id=run_id,
        started_at=now,
        completed_at=_now(),
        goals_evaluated=len(active_goals),
        goals_triggered=len(payments_initiated),
        payments_initiated=payments_initiated,
        payments_skipped=payments_skipped,
        trigger_log=trigger_log,
        narration=narration,
        status="completed",
    )
    _runs.append(agent_run)
    _schedule(_persist_run(agent_run))
    return agent_run


# ── Per-business-agent run ────────────────────────────────────────────────────


async def run_for_agent(
    agent_id: str,
    agent_scope: AgentScope,
    agent_cover=None,
) -> TreasuryAgentRun:
    """Run one evaluation cycle for a specific business agent.

    Evaluates only this agent's goals against the agent's own policy (scope).
    Each payment call passes the agent_id and agent_scope so the orchestrator
    enforces per-agent guardrails. The LLM narrates; code decides.

    Returns immediately if the agent is already running (run-lock guard).
    """

    if _agent_run_lock.get(agent_id):
        raise RuntimeError(
            f"Agent {agent_id} is already running; concurrent runs are not allowed"
        )
    _agent_run_lock[agent_id] = True

    settings = get_settings()
    now = _now()
    run_id = str(uuid.uuid4())
    active_goals = list(_agent_goals.get(agent_id, {}).values())

    payments_initiated: list[str] = []
    payments_skipped: list[str] = []
    trigger_log: list[str] = []

    try:
        for goal in active_goals:
            # Use the agent's max_single_payment as the cap, not the global setting.

            cap_usd = float(agent_scope.max_per_transaction)
            should_fire, reason = evaluate_goal(goal, now, cap_usd)
            trigger_log.append(f"[{goal.name}] {reason}.")

            if not should_fire:
                payments_skipped.append(goal.id)
                continue

            try:
                if goal.service_url:
                    settlement = await orchestrator.process_service_payment(
                        goal.service_url,
                        service_type=goal.service_type or "service",
                        agent_id=agent_id,
                        agent_scope=agent_scope,
                        category=goal.category or goal.purpose,
                    )
                    payments_initiated.append(settlement.invoice_id)
                    trigger_log.append(
                        f"  → x402 settled invoice {settlement.invoice_id[:12]}… "
                        f"amount={settlement.amount} {settlement.currency}"
                    )
                    updated = goal.model_copy(update={"last_triggered_at": now})
                    add_agent_goal(agent_id, updated)
                    continue
                intent = _build_intent(goal, settings)
                payment = await orchestrator.process_payment(
                    intent,
                    agent_id=agent_id,
                    agent_scope=agent_scope,
                    agent_cover=agent_cover,
                )
            except orchestrator.GuardrailBlocked as exc:
                trigger_log.append(f"  blocked: {exc.reason}")
                payments_skipped.append(goal.id)
                add_agent_goal(
                    agent_id, goal.model_copy(update={"last_triggered_at": now})
                )
                continue
            except Exception as exc:
                trigger_log.append(f"  ✗ payment initiation failed: {exc}")
                payments_skipped.append(goal.id)
                continue

            payments_initiated.append(payment.id)
            trigger_log.append(
                f"  → payment {payment.id[:8]}… status={payment.status.value}"
                + (
                    f", rule={payment.policy_decision.rule_fired}"
                    if payment.policy_decision and payment.policy_decision.rule_fired
                    else ""
                )
            )
            if settings.mpt_enabled and payment.status == PaymentStatus.settled:
                await _mint_compliance_attestation(payment, trigger_log, settings)
            updated = goal.model_copy(update={"last_triggered_at": now})
            add_agent_goal(agent_id, updated)

    finally:
        _agent_run_lock[agent_id] = False

    narration = await _narrate(active_goals, trigger_log, payments_initiated, settings)

    agent_run = TreasuryAgentRun(
        id=run_id,
        started_at=now,
        completed_at=_now(),
        goals_evaluated=len(active_goals),
        goals_triggered=len(payments_initiated),
        payments_initiated=payments_initiated,
        payments_skipped=payments_skipped,
        trigger_log=trigger_log,
        narration=narration,
        status="completed",
        agent_id=agent_id,
    )
    _agent_runs.setdefault(agent_id, []).append(agent_run)
    _schedule(_persist_run(agent_run))
    return agent_run


async def load_agent_state_from_db() -> None:
    """Hydrate durable goals and runs after agents have loaded."""
    from sqlalchemy import select
    from .. import db
    from ..models import TreasuryAgentRunRecord, TreasuryGoalRecord

    if db.session_factory is None:
        return
    async with db.session_factory() as session:
        goal_rows = (await session.execute(select(TreasuryGoalRecord))).scalars().all()
        run_rows = (
            (await session.execute(select(TreasuryAgentRunRecord))).scalars().all()
        )
    for row in goal_rows:
        goal = TreasuryGoal(**row.payload)
        if row.agent_id:
            _agent_goals.setdefault(row.agent_id, {}).setdefault(goal.id, goal)
        else:
            _goals.setdefault(goal.id, goal)
    for row in run_rows:
        run = TreasuryAgentRun(**row.payload)
        if row.agent_id:
            bucket = _agent_runs.setdefault(row.agent_id, [])
        else:
            bucket = _runs
        if not any(existing.id == run.id for existing in bucket):
            bucket.append(run)


def _schedule(coro) -> None:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(coro)
            return
    except RuntimeError:
        pass
    coro.close()


async def _persist_goal(goal: TreasuryGoal) -> None:
    from .. import db
    from ..models import TreasuryGoalRecord

    if db.session_factory is None:
        return
    try:
        async with db.session_factory() as session:
            await session.merge(
                TreasuryGoalRecord(
                    id=goal.id,
                    agent_id=goal.agent_id,
                    payload=goal.model_dump(mode="json", by_alias=False),
                    last_triggered_at=goal.last_triggered_at,
                )
            )
            await session.commit()
    except Exception:
        return


async def _delete_goal(goal_id: str) -> None:
    from sqlalchemy import delete
    from .. import db
    from ..models import TreasuryGoalRecord

    if db.session_factory is None:
        return
    async with db.session_factory() as session:
        await session.execute(
            delete(TreasuryGoalRecord).where(TreasuryGoalRecord.id == goal_id)
        )
        await session.commit()


async def _persist_run(run: TreasuryAgentRun) -> None:
    from .. import db
    from ..models import TreasuryAgentRunRecord

    if db.session_factory is None:
        return
    try:
        async with db.session_factory() as session:
            await session.merge(
                TreasuryAgentRunRecord(
                    id=run.id,
                    agent_id=run.agent_id,
                    payload=run.model_dump(mode="json", by_alias=False),
                    started_at=run.started_at,
                    completed_at=run.completed_at,
                )
            )
            await session.commit()
    except Exception:
        return


# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_intent(goal: TreasuryGoal, settings) -> PaymentIntent:
    sender_address = _treasury_address(settings)
    return PaymentIntent(
        from_account=sender_address,
        to=goal.beneficiary_address,
        sender_name="Treasury Agent (autonomous)",
        sender_country=settings.agent_sender_country,
        receiver_name=goal.beneficiary_name,
        receiver_country=goal.beneficiary_country,
        receiver_entity_type=goal.receiver_entity_type,
        purpose=goal.purpose,
        amount=goal.amount,
        currency=goal.currency,
        reference=goal.reference,
    )


def _treasury_address(settings) -> str:
    if not settings.treasury_wallet_seed:
        return settings.treasury_wallet_address or ""
    try:
        from xrpl.wallet import Wallet

        return Wallet.from_seed(settings.treasury_wallet_seed).address
    except Exception:
        return settings.treasury_wallet_address or ""


async def _narrate(
    goals: list[TreasuryGoal],
    trigger_log: list[str],
    payment_ids: list[str],
    settings,
) -> str:
    """LLM narration — explains what was evaluated and initiated. Never decides."""
    deferred = len(goals) - len(payment_ids)
    facts = "\n".join(trigger_log)
    template = (
        f"Treasury agent evaluated {len(goals)} goal(s): "
        f"{len(payment_ids)} initiated, {deferred} deferred.\n{facts}"
    )

    if not settings.openai_api_key:
        return template

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the Treasury Agent's narrator. Write one concise paragraph "
                        "reporting what the agent evaluated and initiated in this cycle. "
                        "You are describing deterministic decisions already made by code — "
                        "you are NOT making any decisions. Be factual and brief."
                    ),
                },
                {"role": "user", "content": facts},
            ],
        )
        return response.choices[0].message.content or template
    except Exception:
        return template


async def _vault_sweep(trigger_log: list[str], settings) -> None:
    """Deterministic idle-treasury sweep using XLS-65 vault.

    If vault_enabled: deposit excess above sweep_threshold into the vault;
    recall when the wallet balance falls below recall_threshold.

    Runs after payment goals are evaluated so payments have priority on
    the wallet balance. The LLM narrates these entries with the others.
    """
    if not settings.vault_enabled:
        return

    state = vault_tool.get_vault_state()
    vault_id = settings.vault_id or state["vault_id"]
    if not vault_id:
        trigger_log.append(
            "[vault] No vault_id configured — run POST /treasury/vault to create one."
        )
        return

    balance = _wallet_balance(settings)

    if balance > settings.vault_sweep_threshold_usd:
        excess = balance - settings.vault_sweep_threshold_usd
        try:
            op = await vault_tool.deposit(vault_id, excess)
            trigger_log.append(
                f"[vault] Swept {op.amount:,.2f} {settings.token_currency} → vault "
                f"(wallet {balance:,.2f} → {balance - op.amount:,.2f}, "
                f"vault now {state['deposited'] + op.amount:,.2f})."
            )
        except Exception as exc:
            trigger_log.append(f"[vault] Deposit failed: {exc}")

    elif balance < settings.vault_recall_threshold_usd:
        needed = settings.vault_sweep_threshold_usd - balance
        try:
            op = await vault_tool.withdraw(vault_id, needed)
            trigger_log.append(
                f"[vault] Recalled {op.amount:,.2f} {settings.token_currency} from vault "
                f"(wallet {balance:,.2f} → {balance + op.amount:,.2f}, "
                f"vault now {max(0.0, state['deposited'] - op.amount):,.2f})."
            )
        except Exception as exc:
            trigger_log.append(f"[vault] Withdraw failed: {exc}")

    else:
        trigger_log.append(
            f"[vault] Balance {balance:,.2f} {settings.token_currency} "
            f"within sweep range [{settings.vault_recall_threshold_usd:,.0f}–"
            f"{settings.vault_sweep_threshold_usd:,.0f}] — no sweep needed."
        )


async def _mint_compliance_attestation(
    payment, trigger_log: list[str], settings
) -> None:
    """Mint 1 COMPLY MPToken to the payment recipient as on-chain compliance proof.

    Called only when mpt_enabled=True and the payment auto-settled (status=settled).
    The issuance_id comes from settings or the in-memory MPT state. If neither
    is configured the step is skipped with a log message pointing to the setup API.
    """
    state = mptoken_tool.get_mpt_state()
    issuance_id = settings.mpt_issuance_id or state["issuance_id"]
    if not issuance_id:
        trigger_log.append(
            "[mpt] No issuance_id — POST /treasury/mpt/issuance to create COMPLY issuance."
        )
        return
    try:
        result = await mptoken_tool.mint_attestation(
            issuance_id=issuance_id,
            recipient=payment.intent.to,
            payment_id=payment.id,
            amount_settled=payment.intent.amount,
        )
        trigger_log.append(
            f"  [mpt] COMPLY attestation minted → {payment.intent.to[:20]}… "
            f"tx={result.tx_hash[:12]}…"
        )
    except Exception as exc:
        trigger_log.append(f"  [mpt] Attestation mint failed: {exc}")


def _wallet_balance(settings) -> float:
    """Return treasury hot-wallet balance for vault sweep decisions.

    Requires an async XRPL account_lines query for real accuracy; returns the
    cached in-memory value as a best-effort approximation until an async path
    is wired (the vault tool debits/credits this on each operation).
    """
    return vault_tool.get_vault_state()["wallet_balance"]


def _now() -> datetime:
    return datetime.now(timezone.utc)
