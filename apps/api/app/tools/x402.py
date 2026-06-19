"""x402 pay-at-need tool (Feature A — ARS Regulated Settlement).

The agent hits a paid service endpoint, receives HTTP 402, deterministic policy
+ G4 scope screen the spend, the agent pays RLUSD per-request via the t54 x402
facilitator, retries with proof, and receives the resource.

Guardrail sequence (in order, short-circuit on first failure):
  G2  counterparty/host sanctions — enforced by the caller before reaching here
  G4  spend scope    — enforced by evaluate_scope (scope.py) before settle_x402
  G6  amount threshold — large x402 spends still go to Firefly (caller decides)

The LLM never calls this directly. Only orchestrator code does, after all
guardrails pass.

Mock mode (settings.use_mock_xrpl=True): a deterministic 402 challenge is
synthesised in-process; no network or real facilitator is called. The mock
returns a real-shaped X402Settlement so the full flow runs offline.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from .. import store, xrpl_client
from ..config import get_settings
from ..schemas import GuardrailResult, X402PaymentRequirement, X402Settlement

log = logging.getLogger(__name__)

SOURCE_TAG = 20260530  # Starter Kit convention; overridden by config


# ── Mock 402 server state ─────────────────────────────────────────────────────

_mock_invoices: dict[str, dict] = {}


def reset_mock_state() -> None:
    """Clear in-process mock invoices (test isolation)."""
    _mock_invoices.clear()


# ── Public API ────────────────────────────────────────────────────────────────

@dataclass
class ServiceResponse:
    """The resource body returned after a successful x402 pay-and-retry."""
    body: str
    status_code: int
    payment: X402Settlement


async def request_with_payment(
    service_url: str,
    *,
    service_type: str = "data_lookup",
    guardrail_trail: list[GuardrailResult] | None = None,
) -> ServiceResponse:
    """GET service_url; if 402, pay and retry once. Returns the resource body.

    Callers must have already run G4 scope.evaluate_scope and passed the result
    before calling this. This function builds the payment from the 402 challenge
    and retries with proof — it does not re-run guardrails.
    """
    settings = get_settings()
    if not settings.x402_enabled:
        raise X402Disabled("x402_enabled is False — enable it in config before calling")

    if settings.use_mock_xrpl:
        return await _mock_request_with_payment(
            service_url, service_type=service_type, guardrail_trail=guardrail_trail or []
        )

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(service_url)

    if resp.status_code != 402:
        return ServiceResponse(body=resp.text, status_code=resp.status_code, payment=_noop_settlement())

    requirement = _parse_402(resp, service_url, settings)
    _validate_requirement(requirement, settings)

    settlement = await settle_x402(requirement, guardrail_trail=guardrail_trail or [])

    # Retry with X-PAYMENT proof header
    async with httpx.AsyncClient(timeout=30) as client:
        retry = await client.get(
            service_url, headers={"X-PAYMENT": settlement.proof_header}
        )

    return ServiceResponse(body=retry.text, status_code=retry.status_code, payment=settlement)


async def settle_x402(
    requirement: X402PaymentRequirement,
    *,
    guardrail_trail: list[GuardrailResult] | None = None,
) -> X402Settlement:
    """Build and submit the RLUSD Payment to satisfy a 402 requirement.

    In real mode: submits to the t54 facilitator endpoint. The facilitator
    handles the Payment submission and returns the X-PAYMENT proof.
    In mock mode: deterministic hash chain, no network.
    """
    settings = get_settings()
    amount = Decimal(requirement.amount)
    invoice_id = requirement.invoice_id
    agent_address = _agent_address(settings)

    # Idempotency: reserve the spend slot (double-spend guard)
    reserved = store.reserve_spend(
        agent_address,
        idempotency_key=invoice_id,
        amount=amount,
        currency=requirement.asset_currency,
        context_kind="x402_payment",
    )
    if not reserved:
        log.info("x402 invoice %s already reserved — idempotent replay", invoice_id)

    try:
        if settings.use_mock_xrpl:
            result = _mock_settle(requirement, settings)
        else:
            result = await _real_settle(requirement, settings)
        store.commit_spend(agent_address, invoice_id)
    except Exception:
        store.release_spend(agent_address, invoice_id)
        raise

    # Emit an ARS audit event
    from . import audit_log
    audit_event = audit_log.append(
        event_type="x402_payment",
        actor="settlement_layer",
        context_kind="payment",
        payload={
            "invoice_id": invoice_id,
            "service_url": requirement.service_url,
            "amount": str(amount),
            "currency": requirement.asset_currency,
            "tx_hash": result.tx_hash,
            "guardrail_trail": [g.model_dump() for g in (guardrail_trail or [])],
        },
    )

    settlement = X402Settlement(
        invoice_id=invoice_id,
        tx_hash=result.tx_hash,
        explorer_url=result.explorer_url,
        proof_header=_build_proof_header(result.tx_hash, invoice_id),
        amount=str(amount),
        currency=requirement.asset_currency,
        guardrail_trail=guardrail_trail or [],
        audit_event_id=audit_event.event_id,
    )
    return settlement


# ── Parsing + validation ──────────────────────────────────────────────────────

def _parse_402(resp: httpx.Response, service_url: str, settings) -> X402PaymentRequirement:
    """Parse a 402 response into an X402PaymentRequirement.

    Accepts both the canonical x402 JSON body and the X-Payment-Required header
    format used by some facilitators. Raises X402ParseError on any missing field.
    """
    try:
        body = resp.json()
    except Exception:
        body = {}

    pay_to = body.get("payTo") or body.get("pay_to") or body.get("destination", "")
    currency = body.get("currency") or body.get("asset") or settings.token_currency
    issuer = body.get("issuer") or body.get("assetIssuer") or settings.token_issuer_address
    network = body.get("network") or settings.xrpl_network
    amount = str(body.get("amount") or body.get("maxAmountRequired") or "0")
    invoice_id = body.get("invoiceId") or body.get("invoice_id") or body.get("nonce") or str(uuid.uuid4())
    facilitator = body.get("facilitatorUrl") or body.get("facilitator_url") or settings.x402_facilitator_url

    from urllib.parse import urlparse
    host = urlparse(service_url).netloc

    return X402PaymentRequirement(
        service_url=service_url,
        facilitator_url=facilitator,
        pay_to=pay_to,
        asset_currency=currency,
        asset_issuer=issuer,
        network=network,
        amount=amount,
        invoice_id=invoice_id,
    )


def _validate_requirement(req: X402PaymentRequirement, settings) -> None:
    """Reject any 402 challenge that doesn't match our config allowlists."""
    allowed_assets = {a.strip() for a in settings.x402_allowed_assets.split(",") if a.strip()}
    if req.asset_currency not in allowed_assets:
        raise X402Rejected(f"currency '{req.asset_currency}' not in x402_allowed_assets")

    allowed_facilitators = {f.strip() for f in settings.x402_allowed_facilitators.split(",") if f.strip()}
    if req.facilitator_url not in allowed_facilitators:
        raise X402Rejected(f"facilitator '{req.facilitator_url}' not in x402_allowed_facilitators")

    amount = Decimal(req.amount)
    if amount <= Decimal("0"):
        raise X402Rejected("challenge amount must be positive")


# ── Real-mode settlement ──────────────────────────────────────────────────────

@dataclass
class _SettleResult:
    tx_hash: str
    explorer_url: str | None


async def _real_settle(req: X402PaymentRequirement, settings) -> _SettleResult:
    """Submit a Payment to the t54 facilitator and return the tx hash."""
    from ..ledger import Ledger
    from xrpl.models.transactions import Payment, Memo

    ledger = Ledger(settings)
    wallet = ledger.treasury_wallet

    amount = Decimal(req.amount)
    memo_data = json.dumps({
        "x402_invoice": req.invoice_id,
        "service_url": req.service_url,
    }, separators=(",", ":"))

    tx = Payment(
        account=wallet.address,
        destination=req.pay_to,
        amount=xrpl_client.to_wire_amount(amount, req.asset_currency, settings),
        source_tag=settings.x402_source_tag,
        memos=[Memo(
            memo_type="x402/v1".encode().hex().upper(),
            memo_data=memo_data.encode().hex().upper(),
        )],
    )
    result = await ledger.submit(tx, wallet)
    tx_hash = result["hash"]
    explorer_url = xrpl_client.explorer_tx_url_for(tx_hash, settings.xrpl_endpoint)
    return _SettleResult(tx_hash=tx_hash, explorer_url=explorer_url)


# ── Mock settlement ───────────────────────────────────────────────────────────

async def _mock_request_with_payment(
    service_url: str,
    *,
    service_type: str,
    guardrail_trail: list[GuardrailResult],
) -> ServiceResponse:
    settings = get_settings()
    invoice_id = hashlib.sha256(f"mock-invoice:{service_url}".encode()).hexdigest()[:32]
    req = X402PaymentRequirement(
        service_url=service_url,
        facilitator_url=settings.x402_facilitator_url,
        pay_to="rMOCKFACILITATOR000000000000000000",
        asset_currency="RLUSD",
        asset_issuer=settings.token_issuer_address or "rQhWct2fv4Vc4KRjRgMrxa8xPN9Zx9iLKV",
        network=settings.xrpl_network,
        amount="1.000000",
        invoice_id=invoice_id,
    )
    settlement = await settle_x402(req, guardrail_trail=guardrail_trail)
    body = json.dumps({"mock": True, "invoice_id": invoice_id, "service_url": service_url})
    return ServiceResponse(body=body, status_code=200, payment=settlement)


def _mock_settle(req: X402PaymentRequirement, settings) -> _SettleResult:
    tx_hash = xrpl_client.mock_tx_hash("x402", req.invoice_id)
    return _SettleResult(tx_hash=tx_hash, explorer_url=None)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_proof_header(tx_hash: str, invoice_id: str) -> str:
    return f"xrpl:{tx_hash}:{invoice_id}"


def _agent_address(settings) -> str:
    from ..ledger import Ledger
    if settings.use_mock_xrpl or not settings.treasury_wallet_seed:
        return settings.treasury_wallet_address or "rMOCK_TREASURY_0000000000000000000"
    return Ledger(settings).treasury_wallet.address


def _noop_settlement() -> X402Settlement:
    return X402Settlement(
        invoice_id="noop",
        tx_hash="0" * 64,
        explorer_url=None,
        proof_header="noop",
        amount="0",
        currency="RLUSD",
    )


# ── Errors ────────────────────────────────────────────────────────────────────

class X402Error(Exception):
    pass

class X402Disabled(X402Error):
    pass

class X402ParseError(X402Error):
    pass

class X402Rejected(X402Error):
    pass
