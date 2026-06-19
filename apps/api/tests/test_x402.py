"""Focused tests for real-mode x402 request behavior."""

from types import SimpleNamespace

import httpx
import pytest

from app.tools import x402


class _FakeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url: str, **_kwargs) -> httpx.Response:
        return httpx.Response(200, text="not payment protected", request=httpx.Request("GET", url))


class _FakeXRPLClient:
    def __init__(self, result: dict) -> None:
        self.result = result

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def request(self, _request):
        return SimpleNamespace(is_successful=lambda: True, result=self.result)


@pytest.mark.asyncio
async def test_real_request_rejects_non_402_without_fake_settlement(monkeypatch) -> None:
    settings = SimpleNamespace(x402_enabled=True, use_mock_xrpl=False)
    monkeypatch.setattr(x402, "get_settings", lambda: settings)
    monkeypatch.setattr(x402.httpx, "AsyncClient", lambda **_kwargs: _FakeClient())

    with pytest.raises(x402.X402Error, match="service returned 200, expected 402"):
        await x402.request_with_payment("https://service.example/resource")


@pytest.mark.asyncio
async def test_demo_proof_requires_validated_exact_invoice_bound_payment(monkeypatch) -> None:
    settings = SimpleNamespace(
        x402_demo_pay_to="rPAYEE",
        x402_demo_price="1.000000",
        token_currency="RLUSD",
        token_issuer_address="rISSUER",
        x402_source_tag=20260530,
        xrpl_endpoint="wss://test",
    )
    invoice_id = "ars-demo-test"
    tx_hash = "A" * 64
    x402._demo_invoice_id = invoice_id
    result = {
        "validated": True,
        "meta": {"TransactionResult": "tesSUCCESS"},
        "tx_json": {
            "TransactionType": "Payment",
            "Account": "rPAYER",
            "Destination": "rPAYEE",
            "DeliverMax": {
                "currency": "524C555344000000000000000000000000000000",
                "issuer": "rISSUER",
                "value": "1.000000",
            },
            "SourceTag": 20260530,
            "Memos": [{"Memo": {"MemoData": invoice_id.encode().hex().upper()}}],
        },
    }
    monkeypatch.setattr(x402.xrpl_client, "async_client", lambda _endpoint: _FakeXRPLClient(result))
    monkeypatch.setattr(x402, "_agent_address", lambda _settings: "rPAYER")

    verified_hash = await x402.verify_demo_proof(
        f"xrpl:{tx_hash}:{invoice_id}", settings
    )

    assert verified_hash == tx_hash
    assert x402._demo_invoice_id is None
    assert await x402.verify_demo_proof(f"xrpl:{tx_hash}:{invoice_id}", settings) == tx_hash
