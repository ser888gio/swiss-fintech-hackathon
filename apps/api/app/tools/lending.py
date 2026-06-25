"""XLS-66 Lending tool — LoanBroker / LoanSet / LoanCreate / LoanRepay (Feature B).

Implements the XLS-66 amendment's loan lifecycle on Devnet. This is the primary
on-chain credit proof for the challenge's Credit & Lending pillar.

Amendment availability:
  XLS-65 (Single Asset Vault) + XLS-66 (Lending) are available on Devnet
  (wss://s.devnet.rippletest.net:51233) at build time. They may not be enabled
  on Testnet. The pre-demo gate (check_amendment_enabled) must pass before the
  pitch; if it fails, set lending_enabled=False and fall back to the XLS-65
  early-payment path in trade_finance.py.

Determinism boundary: the LLM never calls this. Only trade_finance.py calls
loan_create / loan_repay after all guardrails have passed.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal

from .. import xrpl_client
from ..config import get_settings

log = logging.getLogger(__name__)

_QUANTIZE = Decimal("0.000001")

# ── In-memory loan cache (populated from real tx results) ────────────────────

_loans: dict[str, dict] = {}  # loan_id → {status, amount, currency, ...}


# ── Result types ──────────────────────────────────────────────────────────────


@dataclass
class LoanResult:
    loan_id: str
    tx_hash: str
    explorer_url: str | None
    amount: Decimal
    currency: str
    status: str  # "created" | "repaid" | "cancelled"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ── Amendment gate ────────────────────────────────────────────────────────────


async def check_amendment_enabled() -> bool:
    """Query Devnet to confirm the XLS-66 amendment is active.

    Call this before the demo pitch. If False, set lending_enabled=False and
    fall back to the XLS-65 early-payment path (trade_finance.pay_supplier_early
    still works — it just skips the LoanCreate step).
    """
    settings = get_settings()
    try:
        from xrpl.models.requests import ServerInfo

        async with xrpl_client.async_client(settings.lending_xrpl_endpoint) as client:
            resp = await client.request(ServerInfo())
        info = resp.result.get("info", {})
        amendments = info.get("amendments", [])
        # XLS-66 amendment hash — confirm this against the Devnet state before demo.
        # The hash below is illustrative; replace with the real value from
        # https://xrpl.org/known-amendments.html once the amendment is ratified.
        XLS66_AMENDMENT_HASH = (
            "B9E739EB5B4F77B6DFE4B42B403B9F8D2BABB56B5E19E0CE80C6AF2A3B93E1A"
        )
        return XLS66_AMENDMENT_HASH in amendments
    except Exception as exc:
        log.warning("Amendment check failed: %s", exc)
        return False


# ── LoanCreate ────────────────────────────────────────────────────────────────


async def loan_create(
    *,
    invoice_id: str,
    amount: Decimal,
    currency: str,
    loan_broker_address: str | None = None,
) -> LoanResult:
    """XLS-66 LoanCreate: draw from the LoanBroker pool for invoice_id.

    In real mode submits a LoanCreate transaction to the Devnet endpoint.
    Returns a LoanResult with the on-ledger loan sequence (loan_id).
    """
    settings = get_settings()
    if not settings.lending_enabled:
        raise LendingDisabled("lending_enabled is False")

    loan_id = _make_loan_id(invoice_id)
    amount_q = amount.quantize(_QUANTIZE, rounding=ROUND_DOWN)

    return await _real_loan_create(
        loan_id=loan_id,
        invoice_id=invoice_id,
        amount=amount_q,
        currency=currency,
        loan_broker_address=loan_broker_address or settings.lending_loan_broker_address,
        settings=settings,
    )


# ── LoanRepay ─────────────────────────────────────────────────────────────────


async def loan_repay(loan_id: str, *, amount: Decimal) -> LoanResult:
    """XLS-66 LoanRepay: repay the loan, releasing collateral.

    In real mode submits a LoanRepay transaction to Devnet.
    """
    settings = get_settings()
    if not settings.lending_enabled:
        raise LendingDisabled("lending_enabled is False")

    amount_q = amount.quantize(_QUANTIZE, rounding=ROUND_DOWN)

    return await _real_loan_repay(loan_id=loan_id, amount=amount_q, settings=settings)


# ── Real-mode implementations ─────────────────────────────────────────────────


async def _real_loan_create(
    *,
    loan_id: str,
    invoice_id: str,
    amount: Decimal,
    currency: str,
    loan_broker_address: str,
    settings,
) -> LoanResult:
    """Submit XLS-66 LoanCreate to Devnet."""
    from ..ledger import Ledger
    import json

    if not loan_broker_address:
        raise LendingConfigError(
            "lending_loan_broker_address must be set for real-mode LoanCreate"
        )

    ledger = Ledger(settings)
    wallet = ledger.treasury_wallet

    # XLS-66 LoanCreate is a new transaction type. Import lazily — xrpl-py adds
    # it in releases that ship after the amendment activation. If the import
    # fails the amendment is not yet supported; surface the error clearly.
    try:
        from xrpl.models.transactions import LoanCreate
    except ImportError as exc:
        raise LendingNotSupported(
            "xrpl-py does not yet export LoanCreate — upgrade xrpl-py to a "
            "version that supports XLS-66, or set lending_enabled=False."
        ) from exc

    memo_data = json.dumps(
        {"invoice_id": invoice_id, "loan_id": loan_id}, separators=(",", ":")
    )
    from xrpl.models.transactions import Memo

    tx = LoanCreate(
        account=wallet.address,
        loan_broker=loan_broker_address,
        amount=xrpl_client.to_wire_amount(amount, currency, settings),
        source_tag=settings.lending_source_tag,
        memos=[
            Memo(
                memo_type="lending/v1".encode().hex().upper(),
                memo_data=memo_data.encode().hex().upper(),
            )
        ],
    )
    result = await ledger.submit(tx, wallet, endpoint=settings.lending_xrpl_endpoint)
    tx_hash = result["hash"]
    # The loan sequence is in the tx metadata
    actual_loan_id = _parse_loan_sequence(result) or loan_id
    explorer_url = xrpl_client.explorer_tx_url_for(
        tx_hash, settings.lending_xrpl_endpoint
    )

    _loans[actual_loan_id] = {
        "status": "created",
        "amount": str(amount),
        "currency": currency,
        "invoice_id": invoice_id,
        "create_tx_hash": tx_hash,
    }

    _emit_audit("loan_created", actual_loan_id, amount, currency, tx_hash)
    return LoanResult(
        loan_id=actual_loan_id,
        tx_hash=tx_hash,
        explorer_url=explorer_url,
        amount=amount,
        currency=currency,
        status="created",
    )


async def _real_loan_repay(*, loan_id: str, amount: Decimal, settings) -> LoanResult:
    """Submit XLS-66 LoanRepay to Devnet."""
    from ..ledger import Ledger

    try:
        from xrpl.models.transactions import LoanRepay
    except ImportError as exc:
        raise LendingNotSupported(
            "xrpl-py does not yet export LoanRepay — upgrade or set lending_enabled=False."
        ) from exc

    ledger = Ledger(settings)
    wallet = ledger.treasury_wallet

    loan = _loans.get(loan_id, {})
    currency = loan.get("currency", settings.token_currency)

    tx = LoanRepay(
        account=wallet.address,
        loan_id=loan_id,
        amount=xrpl_client.to_wire_amount(amount, currency, settings),
        source_tag=settings.lending_source_tag,
    )
    result = await ledger.submit(tx, wallet, endpoint=settings.lending_xrpl_endpoint)
    tx_hash = result["hash"]
    explorer_url = xrpl_client.explorer_tx_url_for(
        tx_hash, settings.lending_xrpl_endpoint
    )

    if loan_id in _loans:
        _loans[loan_id]["status"] = "repaid"

    _emit_audit("loan_repaid", loan_id, amount, currency, tx_hash)
    return LoanResult(
        loan_id=loan_id,
        tx_hash=tx_hash,
        explorer_url=explorer_url,
        amount=amount,
        currency=currency,
        status="repaid",
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_loan_id(invoice_id: str) -> str:
    return hashlib.sha256(f"loan:{invoice_id}".encode()).hexdigest()[:32]


def _parse_loan_sequence(result: dict) -> str | None:
    """Extract the LoanSequence (loan_id) from LoanCreate metadata."""
    for node in result.get("meta", {}).get("AffectedNodes", []):
        created = node.get("CreatedNode", {})
        if created.get("LedgerEntryType") in ("Loan", "LoanOffer"):
            return str(
                created.get("LedgerIndex")
                or created.get("NewFields", {}).get("LoanSequence", "")
            )
    return None


def _emit_audit(
    event_type: str, loan_id: str, amount: Decimal, currency: str, tx_hash: str
) -> None:
    from . import audit_log

    audit_log.append(
        event_type=event_type,
        actor="settlement_layer",
        context_kind="loan_underwrite",
        payload={
            "loan_id": loan_id,
            "amount": str(amount),
            "currency": currency,
            "tx_hash": tx_hash,
        },
    )


# ── Errors ────────────────────────────────────────────────────────────────────


class LendingError(Exception):
    pass


class LendingDisabled(LendingError):
    pass


class LendingNotSupported(LendingError):
    pass


class LendingConfigError(LendingError):
    pass


class LoanNotFound(LendingError):
    pass
