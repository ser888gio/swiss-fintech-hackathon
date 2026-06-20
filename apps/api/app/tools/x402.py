"""x402 pay-at-need tool (Feature A — ARS Regulated Settlement).

The agent hits a paid service endpoint, receives HTTP 402, deterministic policy
+ full G4 scope screen the quoted spend, the Python API submits RLUSD directly
with xrpl-py, retries with proof, and receives the resource.

Guardrail sequence (in order, short-circuit on first failure):
  G1  KYA            — enforced by the orchestrator after challenge fetch
  G4  spend scope    — enforced by evaluate_scope (scope.py) before settle_x402
  G6  amount threshold — review outcomes hard-block on this micropayment path

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
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from .. import xrpl_client
from ..config import get_settings
from ..schemas import GuardrailResult, X402PaymentRequirement, X402Settlement

log = logging.getLogger(__name__)

SOURCE_TAG = 20260530  # Starter Kit convention; overridden by config


# ── Mock 402 server state ─────────────────────────────────────────────────────

_mock_invoices: dict[str, dict] = {}
_demo_invoice_id: str | None = None
_demo_last_verified: tuple[str, str] | None = None


def reset_mock_state() -> None:
    """Clear in-process mock invoices (test isolation)."""
    global _demo_invoice_id, _demo_last_verified
    _mock_invoices.clear()
    _demo_invoice_id = None
    _demo_last_verified = None


def issue_demo_requirement(service_url: str, settings) -> X402PaymentRequirement:
    """Issue one exact RLUSD challenge for the built-in Testnet demo merchant."""
    global _demo_invoice_id
    if not settings.x402_demo_pay_to:
        raise X402Error("x402_demo_pay_to is not configured")
    _demo_invoice_id = f"ars-demo-{uuid.uuid4()}"
    return X402PaymentRequirement(
        service_url=service_url,
        facilitator_url=settings.x402_facilitator_url,
        pay_to=settings.x402_demo_pay_to,
        asset_currency=settings.token_currency,
        asset_issuer=settings.token_issuer_address,
        network=settings.xrpl_network,
        amount=settings.x402_demo_price,
        invoice_id=_demo_invoice_id,
        source_tag=settings.x402_source_tag,
    )


async def verify_demo_proof(proof_header: str, settings) -> str:
    """Verify the demo payment independently against the validated ledger."""
    global _demo_invoice_id, _demo_last_verified
    match = re.fullmatch(r"xrpl:([A-Fa-f0-9]{64}):(.+)", proof_header)
    if not match:
        raise X402Error("invalid x402 proof header or invoice binding")
    tx_hash = match.group(1).upper()
    proof_invoice_id = match.group(2)
    if _demo_last_verified == (proof_invoice_id, tx_hash):
        return tx_hash

    invoice_id = _demo_invoice_id
    if not invoice_id:
        raise X402Error("no demo invoice is pending")
    if proof_invoice_id != invoice_id:
        raise X402Error("invalid x402 proof header or invoice binding")

    from xrpl.models.requests import Tx

    async with xrpl_client.async_client(settings.xrpl_endpoint) as client:
        response = await client.request(Tx(transaction=tx_hash))
    if not response.is_successful():
        raise X402Error("payment transaction was not found on XRPL Testnet")

    result = response.result
    tx = result.get("tx_json") or result
    meta = result.get("meta") or {}
    # XRPL API v2 renames Payment.Amount to DeliverMax in transaction responses.
    amount = tx.get("Amount") or tx.get("DeliverMax") or {}
    expected_currency = xrpl_client.currency_code(settings.token_currency).upper()
    checks = {
        "validated": result.get("validated") is True,
        "tesSUCCESS": meta.get("TransactionResult") == "tesSUCCESS",
        "payment": tx.get("TransactionType") == "Payment",
        "payer": tx.get("Account") == _agent_address(settings),
        "destination": tx.get("Destination") == settings.x402_demo_pay_to,
        "currency": isinstance(amount, dict)
        and str(amount.get("currency", "")).upper() == expected_currency,
        "issuer": isinstance(amount, dict)
        and amount.get("issuer") == settings.token_issuer_address,
        "amount": isinstance(amount, dict)
        and Decimal(str(amount.get("value", "0"))) == Decimal(settings.x402_demo_price),
        "source_tag": tx.get("SourceTag") == settings.x402_source_tag,
        "invoice_memo": _tx_contains_invoice(tx, invoice_id),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise X402Error(f"payment proof failed ledger checks: {', '.join(failed)}")

    _demo_last_verified = (invoice_id, tx_hash)
    _demo_invoice_id = None
    return tx_hash


def _tx_contains_invoice(tx: dict, invoice_id: str) -> bool:
    for wrapper in tx.get("Memos") or []:
        memo = wrapper.get("Memo") or {}
        raw = memo.get("MemoData")
        if not raw:
            continue
        try:
            decoded = bytes.fromhex(raw).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        if invoice_id in decoded:
            return True
    return False


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
    requirement = await fetch_requirement(service_url)
    settlement = await settle_x402(requirement, guardrail_trail=guardrail_trail or [])
    return await retry_with_proof(requirement, settlement)


async def fetch_requirement(service_url: str) -> X402PaymentRequirement:
    """Fetch, parse, and validate a 402 challenge without moving money."""
    settings = get_settings()
    if not settings.x402_enabled:
        raise X402Disabled("x402_enabled is False — enable it in config before calling")
    if settings.use_mock_xrpl:
        requirement = _mock_requirement(service_url, settings)
        _validate_requirement(requirement, settings)
        return requirement
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(service_url)
    if response.status_code != 402:
        raise X402Error(
            f"service returned {response.status_code}, expected 402 — no payment made"
        )
    requirement = _parse_402(response, service_url, settings)
    _validate_requirement(requirement, settings)
    return requirement


async def retry_with_proof(
    requirement: X402PaymentRequirement,
    settlement: X402Settlement,
) -> ServiceResponse:
    """Retry a protected resource and require merchant proof acceptance."""
    settings = get_settings()
    if settings.use_mock_xrpl:
        return ServiceResponse(
            body=json.dumps({
                "mock": True,
                "invoice_id": requirement.invoice_id,
                "service_url": requirement.service_url,
                "verified": True,
            }),
            status_code=200,
            payment=settlement,
        )
    async with httpx.AsyncClient(timeout=30) as client:
        retry = await client.get(
            requirement.service_url,
            headers={"X-PAYMENT": settlement.proof_header},
        )
    if not 200 <= retry.status_code < 300:
        raise X402Error(
            f"merchant rejected payment proof with HTTP {retry.status_code}"
        )
    return ServiceResponse(body=retry.text, status_code=retry.status_code, payment=settlement)


async def settle_x402(
    requirement: X402PaymentRequirement,
    *,
    guardrail_trail: list[GuardrailResult] | None = None,
    agent_id: str | None = None,
) -> X402Settlement:
    """Build and submit the RLUSD Payment to satisfy a 402 requirement.

    In real mode: submits a direct issued-currency Payment with xrpl-py.
    In mock mode: deterministic hash chain, no network.
    """
    settings = get_settings()
    amount = Decimal(requirement.amount)
    invoice_id = requirement.invoice_id
    if settings.use_mock_xrpl:
        result = _mock_settle(requirement, settings)
    else:
        result = await _real_settle(requirement, settings)

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
        agent_id=agent_id,
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
    source_tag = body.get("sourceTag") or body.get("source_tag")
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
        source_tag=int(source_tag) if source_tag is not None else None,
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
    if settings.token_issuer_address and req.asset_issuer != settings.token_issuer_address:
        raise X402Rejected("challenge issuer does not match configured token issuer")
    if req.network.lower() != settings.xrpl_network.lower():
        raise X402Rejected(
            f"challenge network '{req.network}' does not match '{settings.xrpl_network}'"
        )


# ── Real-mode settlement ──────────────────────────────────────────────────────

@dataclass
class _SettleResult:
    tx_hash: str
    explorer_url: str | None


async def _real_settle(req: X402PaymentRequirement, settings) -> _SettleResult:
    """Submit a direct issued-currency Payment and return the tx hash."""
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
        source_tag=req.source_tag or settings.x402_source_tag,
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
    req = _mock_requirement(service_url, settings)
    settlement = await settle_x402(req, guardrail_trail=guardrail_trail)
    body = json.dumps({"mock": True, "invoice_id": req.invoice_id, "service_url": service_url})
    return ServiceResponse(body=body, status_code=200, payment=settlement)


def _mock_requirement(service_url: str, settings) -> X402PaymentRequirement:
    invoice_id = f"mock-{uuid.uuid4()}"
    slug = service_url.rstrip("/").split("/")[-1].split("?")[0]
    prices = {
        "repair-yard": "2.000000",
        "customs": "5.000000",
        "port-authority": "2.500000",
        "bunker-fuel": "2.750000",
        "marine-insurance": "3.000000",
        "repair-yard-over-threshold": "4.000000",
    }
    return X402PaymentRequirement(
        service_url=service_url,
        facilitator_url=settings.x402_facilitator_url,
        pay_to=f"rMOCK{hashlib.sha256(slug.encode()).hexdigest()[:29]}",
        asset_currency="RLUSD",
        asset_issuer=settings.token_issuer_address
        or "rQhWct2fv4Vc4KRjRgMrxa8xPN9Zx9iLKV",
        network=settings.xrpl_network,
        amount=(
            "4.000000"
            if slug == "repair-yard" and "price=4.000000" in service_url
            else prices.get(slug, "1.000000")
        ),
        invoice_id=invoice_id,
        source_tag=settings.x402_source_tag,
    )


_MERCHANTS = {
    "repair-yard": ("x402_repair_yard_pay_to", "2.000000", 20260601),
    "customs": ("x402_customs_pay_to", "5.000000", 20260602),
    "port-authority": ("x402_port_authority_pay_to", "2.500000", 20260603),
    "bunker-fuel": ("x402_bunker_fuel_pay_to", "2.750000", 20260604),
    "marine-insurance": ("x402_marine_insurance_pay_to", "3.000000", 20260605),
}


def issue_merchant_requirement(
    slug: str,
    service_url: str,
    settings,
    *,
    price_override: str | None = None,
) -> X402PaymentRequirement:
    """Issue a fresh challenge for one simulated in-API counterparty."""
    if slug not in _MERCHANTS:
        raise X402Error(f"unknown merchant '{slug}'")
    setting_name, price, source_tag = _MERCHANTS[slug]
    pay_to = getattr(settings, setting_name, "")
    if not pay_to:
        if settings.use_mock_xrpl:
            pay_to = f"rMOCK{hashlib.sha256(slug.encode()).hexdigest()[:29]}"
        else:
            raise X402Error(f"{setting_name} is not configured")
    invoice_id = f"maersk-{slug}-{uuid.uuid4()}"
    requirement = X402PaymentRequirement(
        service_url=service_url,
        facilitator_url=settings.x402_facilitator_url,
        pay_to=pay_to,
        asset_currency="RLUSD",
        asset_issuer=settings.token_issuer_address,
        network=settings.xrpl_network,
        amount=price_override or price,
        invoice_id=invoice_id,
        source_tag=source_tag,
    )
    _mock_invoices[invoice_id] = {
        "slug": slug,
        "requirement": requirement,
        "verified_tx_hash": None,
    }
    return requirement


async def verify_merchant_proof(proof_header: str, slug: str, settings) -> str:
    """Verify exact destination/asset/amount/tag/invoice on a validated ledger."""
    match = re.fullmatch(r"xrpl:([A-Fa-f0-9]{64}):(.+)", proof_header)
    if not match:
        raise X402Error("invalid x402 proof header")
    tx_hash = match.group(1).upper()
    invoice_id = match.group(2)
    state = _mock_invoices.get(invoice_id)
    if not state or state["slug"] != slug:
        raise X402Error("unknown or mismatched merchant invoice")
    if state["verified_tx_hash"] == tx_hash:
        return tx_hash
    requirement: X402PaymentRequirement = state["requirement"]
    if settings.use_mock_xrpl:
        state["verified_tx_hash"] = tx_hash
        return tx_hash

    from xrpl.models.requests import Tx
    async with xrpl_client.async_client(settings.xrpl_endpoint) as client:
        response = await client.request(Tx(transaction=tx_hash))
    if not response.is_successful():
        raise X402Error("payment transaction was not found on XRPL Testnet")
    result = response.result
    tx = result.get("tx_json") or result
    meta = result.get("meta") or {}
    amount = tx.get("Amount") or tx.get("DeliverMax") or {}
    checks = {
        "validated": result.get("validated") is True,
        "tesSUCCESS": meta.get("TransactionResult") == "tesSUCCESS",
        "payment": tx.get("TransactionType") == "Payment",
        "payer": tx.get("Account") == _agent_address(settings),
        "destination": tx.get("Destination") == requirement.pay_to,
        "currency": isinstance(amount, dict)
        and str(amount.get("currency", "")).upper()
        == xrpl_client.currency_code(requirement.asset_currency).upper(),
        "issuer": isinstance(amount, dict)
        and amount.get("issuer") == requirement.asset_issuer,
        "amount": isinstance(amount, dict)
        and Decimal(str(amount.get("value", "0"))) == Decimal(requirement.amount),
        "source_tag": tx.get("SourceTag") == requirement.source_tag,
        "invoice_memo": _tx_contains_invoice(tx, invoice_id),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise X402Error(f"payment proof failed ledger checks: {', '.join(failed)}")
    state["verified_tx_hash"] = tx_hash
    return tx_hash


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


# ── Errors ────────────────────────────────────────────────────────────────────

class X402Error(Exception):
    pass

class X402Disabled(X402Error):
    pass

class X402ParseError(X402Error):
    pass

class X402Rejected(X402Error):
    pass
