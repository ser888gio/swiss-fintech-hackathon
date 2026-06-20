from types import SimpleNamespace
from decimal import Decimal

import pytest

from app import store
from app.agents import orchestrator
from app.agents import treasury_agent
from app.policy.scope import AgentScope
from app.routes import agents as agent_routes
from app.schemas import X402PaymentRequirement, X402Settlement


def _settings():
    return SimpleNamespace(
        treasury_wallet_address="rTREASURY",
        credential_kyc_enabled=False,
        policy_threshold_usd=500.0,
        policy_compliance_flag_score=60,
        insurance_enabled=False,
    )


def _requirement(amount: str = "2.000000", host: str = "api.example"):
    return X402PaymentRequirement(
        service_url=f"https://{host}/merchants/repair-yard",
        facilitator_url="https://facilitator.example",
        pay_to="rREPAIR",
        asset_currency="RLUSD",
        asset_issuer="rISSUER",
        network="xrpl:1",
        amount=amount,
        invoice_id=f"invoice-{amount}-{host}",
        source_tag=20260601,
    )


def _scope(**overrides):
    data = dict(
        max_per_transaction=Decimal("5"),
        max_per_day=Decimal("20"),
        requires_approval_above=Decimal("3"),
        allowed_service_hosts=["api.example"],
        allowed_categories=["repairs"],
        allowed_assets=["RLUSD"],
        allowed_network="xrpl:1",
        require_known_merchant=True,
    )
    data.update(overrides)
    return AgentScope(**data)


@pytest.fixture(autouse=True)
def reset_state():
    store._service_payments.clear()
    store._agent_reservations.clear()
    yield
    store._service_payments.clear()
    store._agent_reservations.clear()


def _patch_common(monkeypatch, requirement):
    monkeypatch.setattr(orchestrator, "get_settings", _settings)
    monkeypatch.setattr(
        orchestrator.credentials,
        "verify_kyc",
        lambda _address: _async_value(SimpleNamespace(verified=True)),
    )
    monkeypatch.setattr(
        orchestrator.x402_tool,
        "fetch_requirement",
        lambda _url: _async_value(requirement),
    )


async def _async_value(value):
    return value


@pytest.mark.asyncio
async def test_policy_uses_real_402_amount_before_settlement(monkeypatch):
    requirement = _requirement("6.000000")
    _patch_common(monkeypatch, requirement)
    called = False

    async def settle(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(orchestrator.x402_tool, "settle_x402", settle)

    with pytest.raises(orchestrator.GuardrailBlocked, match="per-transaction cap"):
        await orchestrator.process_service_payment(
            requirement.service_url,
            agent_id="repair-bot",
            agent_scope=_scope(),
            category="repairs",
            service_type="repairs",
        )

    assert called is False
    record = store.list_service_payments("repair-bot")[0]
    assert record.status == "blocked"
    assert record.amount == "6.000000"


@pytest.mark.asyncio
async def test_x402_approval_threshold_is_hard_block(monkeypatch):
    requirement = _requirement("4.000000")
    _patch_common(monkeypatch, requirement)
    called = False

    async def settle(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(orchestrator.x402_tool, "settle_x402", settle)
    with pytest.raises(orchestrator.GuardrailBlocked, match="over approval threshold"):
        await orchestrator.process_service_payment(
            requirement.service_url,
            agent_id="repair-bot",
            agent_scope=_scope(),
            category="repairs",
            service_type="repairs",
        )
    assert called is False
    assert store.agent_payments_sum("repair-bot", __import__("datetime").datetime.min.replace(tzinfo=__import__("datetime").timezone.utc), "RLUSD") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requirement", "scope", "rule"),
    [
        (_requirement(host="evil.example"), _scope(), "host_not_in_allowlist"),
        (
            _requirement(),
            _scope(allowed_assets=["XRP"]),
            "asset_not_allowed",
        ),
        (
            _requirement(),
            _scope(allowed_network="xrpl:2"),
            "network_not_allowed",
        ),
        (
            _requirement(),
            _scope(blocked_addresses=["rREPAIR"]),
            "payee_on_blocklist",
        ),
    ],
)
async def test_full_scope_violations_block_before_settlement(
    monkeypatch, requirement, scope, rule
):
    _patch_common(monkeypatch, requirement)
    called = False

    async def settle(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(orchestrator.x402_tool, "settle_x402", settle)
    with pytest.raises(orchestrator.GuardrailBlocked) as exc:
        await orchestrator.process_service_payment(
            requirement.service_url,
            agent_id="repair-bot",
            agent_scope=scope,
            category="repairs",
            service_type="repairs",
        )
    assert exc.value.guardrail == rule
    assert called is False


@pytest.mark.asyncio
async def test_under_threshold_settles_and_commits_agent_spend(monkeypatch):
    requirement = _requirement("2.000000")
    _patch_common(monkeypatch, requirement)

    async def settle(_req, *, guardrail_trail, agent_id):
        return X402Settlement(
            invoice_id=requirement.invoice_id,
            tx_hash="A" * 64,
            proof_header=f"xrpl:{'A' * 64}:{requirement.invoice_id}",
            amount=requirement.amount,
            currency="RLUSD",
            guardrail_trail=guardrail_trail,
            agent_id=agent_id,
        )

    monkeypatch.setattr(orchestrator.x402_tool, "settle_x402", settle)
    monkeypatch.setattr(
        orchestrator.x402_tool,
        "retry_with_proof",
        lambda *_args: _async_value(SimpleNamespace(status_code=200)),
    )
    settlement = await orchestrator.process_service_payment(
        requirement.service_url,
        agent_id="repair-bot",
        agent_scope=_scope(),
        category="repairs",
        service_type="repairs",
    )
    assert settlement.tx_hash == "A" * 64
    record = store.list_service_payments("repair-bot")[0]
    assert record.status == "settled"
    assert record.tx_hash == "A" * 64
    assert store._agent_reservations["repair-bot"][0]["status"] == "committed"


@pytest.mark.asyncio
async def test_mock_controller_run_persists_five_settlements_and_one_block(monkeypatch):
    settings = SimpleNamespace(
        agent_enabled=True,
        openai_api_key="",
        openai_model="unused",
        mpt_enabled=False,
        vault_enabled=False,
        treasury_wallet_address="rTREASURY",
        treasury_wallet_seed="",
        credential_kyc_enabled=False,
        policy_threshold_usd=500.0,
        policy_compliance_flag_score=60,
        insurance_enabled=False,
        x402_enabled=True,
        use_mock_xrpl=True,
        x402_facilitator_url="https://facilitator.example",
        x402_allowed_facilitators="https://facilitator.example",
        x402_allowed_assets="RLUSD",
        token_issuer_address="rISSUER",
        xrpl_network="xrpl:1",
        x402_source_tag=20260601,
    )
    monkeypatch.setattr(agent_routes, "get_settings", lambda: settings)
    monkeypatch.setattr(treasury_agent, "get_settings", lambda: settings)
    monkeypatch.setattr(orchestrator, "get_settings", lambda: settings)
    monkeypatch.setattr(orchestrator.x402_tool, "get_settings", lambda: settings)
    monkeypatch.setattr(
        orchestrator.credentials,
        "verify_kyc",
        lambda _address: _async_value(SimpleNamespace(verified=True)),
    )
    agent_routes._agents.clear()
    treasury_agent._agent_goals.clear()
    treasury_agent._agent_runs.clear()
    request = SimpleNamespace(
        base_url="http://testserver/",
        url=SimpleNamespace(netloc="testserver"),
    )
    seeded = await agent_routes.seed_maersk(request)
    assert len(seeded) == 6

    run = await agent_routes.run_controller()

    assert run.goals_evaluated == 6
    assert run.goals_triggered == 5
    records = store.list_service_payments()
    assert len([r for r in records if r.status == "settled"]) == 5
    assert len([r for r in records if r.status == "blocked"]) == 1
    assert {r.agent_id for r in records} == set(agent_routes.MAERSK_SUBAGENTS)
