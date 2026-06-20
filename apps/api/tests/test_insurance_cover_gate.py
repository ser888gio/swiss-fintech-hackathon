from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents import orchestrator
from app.schemas import ComplianceResult, CredentialStatus, ExecutionResult, PaymentIntent, PremiumQuote, QuoteDecision, RouteQuote


def _settings(**overrides):
    data = {
        "token_currency": "USD",
        "policy_threshold_usd": 10000.0,
        "policy_compliance_flag_score": 60,
        "insurance_enabled": True,
        "insurance_cover_required_above_usd": None,
        "use_mock_xrpl": True,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _intent(**overrides) -> PaymentIntent:
    data = {
        "from": "rAGENT",
        "to": "rRECEIVER",
        "senderName": "Sender",
        "senderCountry": "CH",
        "receiverName": "Receiver",
        "receiverCountry": "US",
        "receiverEntityType": "company",
        "purpose": "supplier_payment",
        "amount": 1500.0,
        "currency": "USD",
        "reference": "INV-001",
    }
    data.update(overrides)
    return PaymentIntent(**data)


@pytest.fixture(autouse=True)
def reset_store():
    from app import store

    store._payments.clear()
    store._logs.clear()
    yield
    store._payments.clear()
    store._logs.clear()


@pytest.mark.anyio
async def test_cover_required_auto_binds_before_settle(monkeypatch):
    from app.tools import audit, compliance, credentials, execution, routing
    from app.tools import insurance as insurance_tool

    async def fake_route(intent, currency):
        return RouteQuote(source_amount=1500, dest_amount=1500, rate=1.0, path_summary="1:1", estimated_fee=0)

    async def fake_usd(amount, currency):
        return 1500.0

    async def fake_kyc(subject):
        return CredentialStatus(checked=False, verified=False, reason="disabled")

    async def fake_audit(route, screen, decision, **kwargs):
        return "audit"

    async def fake_execute(*args, **kwargs):
        return ExecutionResult(tx_hash="A" * 64, explorer_url=None, status="settled")

    monkeypatch.setattr(orchestrator, "get_settings", lambda: _settings())
    monkeypatch.setattr(routing, "get_fx_path", fake_route)
    monkeypatch.setattr(routing, "convert_to_usd", fake_usd)
    monkeypatch.setattr(credentials, "verify_kyc", fake_kyc)
    monkeypatch.setattr(compliance, "check_compliance", lambda intent, credential=None: ComplianceResult(aml_score=10, sanctioned=False, flags=[], explanation="clean"))
    monkeypatch.setattr(audit, "write_audit", fake_audit)
    monkeypatch.setattr(execution, "execute_payment", fake_execute)

    calls: list[str] = []

    def fake_quote(request):
        calls.append("quote")
        return PremiumQuote(
            decision=QuoteDecision.offer,
            premium="12.000000",
            lines={"merchant_default": "12.000000"},
            pd=0.03,
            credibility=0.0,
            reason="Coverage offered.",
            receipt_hash="b" * 64,
        )

    async def fake_bind(request):
        calls.append("bind")
        from app.schemas import InsurancePremiumRecord
        from datetime import datetime, timezone

        return InsurancePremiumRecord(
            id="premium-1",
            job_id=request.job_id,
            agent_address=request.agent_address,
            premium_amount=request.quote.premium,
            currency=request.currency,
            tx_hash="B" * 64,
            explorer_url=None,
            score_band=request.score_band,
            created_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr(insurance_tool, "quote", fake_quote)
    monkeypatch.setattr(insurance_tool, "bind", fake_bind)

    payment = await orchestrator.process_payment(_intent(coverRequired=True))

    assert payment.cover is not None
    assert payment.status.value == "settled"
    assert calls == ["quote", "bind"]


@pytest.mark.anyio
async def test_cover_disabled_leaves_existing_flow_unchanged(monkeypatch):
    from app.tools import audit, compliance, credentials, execution, routing
    from app.tools import insurance as insurance_tool

    async def fake_route(intent, currency):
        return RouteQuote(source_amount=500, dest_amount=500, rate=1.0, path_summary="1:1", estimated_fee=0)

    async def fake_usd(amount, currency):
        return 500.0

    async def fake_kyc(subject):
        return CredentialStatus(checked=False, verified=False, reason="disabled")

    async def fake_audit(route, screen, decision, **kwargs):
        return "audit"

    async def fake_execute(*args, **kwargs):
        return ExecutionResult(tx_hash="A" * 64, explorer_url=None, status="settled")

    monkeypatch.setattr(orchestrator, "get_settings", lambda: _settings())
    monkeypatch.setattr(routing, "get_fx_path", fake_route)
    monkeypatch.setattr(routing, "convert_to_usd", fake_usd)
    monkeypatch.setattr(credentials, "verify_kyc", fake_kyc)
    monkeypatch.setattr(compliance, "check_compliance", lambda intent, credential=None: ComplianceResult(aml_score=10, sanctioned=False, flags=[], explanation="clean"))
    monkeypatch.setattr(audit, "write_audit", fake_audit)
    monkeypatch.setattr(execution, "execute_payment", fake_execute)

    def should_not_run(_request):
        raise AssertionError("insurance quote should not run")

    monkeypatch.setattr(insurance_tool, "quote", should_not_run)

    payment = await orchestrator.process_payment(_intent())

    assert payment.cover is None
    assert payment.status.value == "settled"
