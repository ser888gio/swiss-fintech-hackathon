"""Trade Finance tool — on-chain credit / early supplier payment (Feature B).

Lifecycle of a trade-finance receivable:
  1. register_receivable   — record a 90-day invoice; status → registered
  2. pay_supplier_early    — draw from the XLS-65 vault; pay supplier at discount
                             status → credit_drawn → supplier_paid → awaiting_maturity
  3. collect_repayment     — buyer repays face value; replenish vault
                             status → repayment_received → credit_settled → closed

The deterministic rule that fires step 2 or 3 lives in treasury_agent.py (the
trigger). The LLM only narrates the outcome; it never decides timing or amounts.

Guardrails applied before step 2:
  G4 spend scope  — the early-payment amount is checked via scope.evaluate_scope
  G6 threshold    — large early-payments still escalate to Firefly

XLS-65 vault is used for the credit pool (via vault.py). XLS-66 LoanCreate/
LoanRepay is delegated to lending.py when lending_enabled=True.

Mock mode: full state machine runs in-process; no network calls. All operations
return deterministic tx hashes.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal

from .. import db, store, xrpl_client
from ..config import get_settings
from ..schemas import GuardrailResult, Receivable, ReceivableCreate, ReceivableStatus
from ..tools import vault as vault_tool

log = logging.getLogger(__name__)

_QUANTIZE = Decimal("0.000001")

# ── In-memory receivable store ────────────────────────────────────────────────
_receivables: dict[str, Receivable] = {}   # id → Receivable
_by_invoice: dict[str, str] = {}           # invoice_id → id


def reset_mock_state() -> None:
    _receivables.clear()
    _by_invoice.clear()


# ── register_receivable ───────────────────────────────────────────────────────

async def register_receivable(create: ReceivableCreate) -> Receivable:
    """Record a new trade-finance receivable. Status → registered.

    Does not touch the vault or the XRPL; simply stores the claim so the agent
    can later call pay_supplier_early when the timing is right.
    """
    settings = get_settings()
    if not settings.trade_finance_enabled:
        raise TradeFinanceDisabled("trade_finance_enabled is False")

    if create.invoice_id in _by_invoice:
        return _receivables[_by_invoice[create.invoice_id]]

    record_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    rec = Receivable(
        id=record_id,
        invoice_id=create.invoice_id,
        buyer=create.buyer,
        supplier=create.supplier,
        amount=create.amount,
        discount_rate=create.discount_rate,
        due_date=create.due_date,
        status=ReceivableStatus.registered,
        created_at=now,
        updated_at=now,
    )
    _store(rec)
    _schedule_persist(rec)
    _emit_audit("receivable_registered", rec)
    return rec


# ── pay_supplier_early ────────────────────────────────────────────────────────

async def pay_supplier_early(
    invoice_id: str,
    *,
    guardrail_trail: list[GuardrailResult] | None = None,
    vault_id: str | None = None,
) -> Receivable:
    """Draw credit from the vault pool and pay the supplier at a discount.

    Flow:
      VaultWithdraw(face_value)              — pull funds from pool
      Payment(supplier, face*(1-discount))   — pay supplier; treasury keeps discount
      LoanCreate(face_value)                 — XLS-66 (if lending_enabled)
    Status progression: registered → funds_reserved → credit_drawn → supplier_paid
                        → awaiting_maturity
    """
    settings = get_settings()
    if not settings.trade_finance_enabled:
        raise TradeFinanceDisabled("trade_finance_enabled is False")

    rec = _get_by_invoice(invoice_id)
    if rec.status not in (ReceivableStatus.registered, ReceivableStatus.funds_reserved):
        raise InvalidReceivableState(f"receivable {invoice_id} is in state {rec.status}; cannot pay early")

    face = Decimal(rec.amount).quantize(_QUANTIZE, rounding=ROUND_DOWN)
    discount = Decimal(rec.discount_rate).quantize(_QUANTIZE, rounding=ROUND_DOWN)
    supplier_amount = (face * (Decimal("1") - discount)).quantize(_QUANTIZE, rounding=ROUND_DOWN)

    # Idempotency guard via spend reservation
    idempotency_key = f"trade_finance:pay:{invoice_id}"
    store.reserve_spend(
        agent_address=_agent_address(settings),
        idempotency_key=idempotency_key,
        amount=face,
        currency=settings.token_currency,
        context_kind="trade_finance",
    )

    rec = _update(rec, status=ReceivableStatus.funds_reserved)

    try:
        # VaultWithdraw: draw face value from the credit pool
        effective_vault_id = vault_id or settings.vault_id
        if not settings.use_mock_xrpl:
            effective_vault_id = vault_tool.require_vault_id(effective_vault_id)
        else:
            effective_vault_id = effective_vault_id or "mock-vault"
        withdrawal = await vault_tool.withdraw(effective_vault_id, float(face))
        if Decimal(str(withdrawal.amount)) < face:
            raise InsufficientVaultLiquidity(
                f"vault released {withdrawal.amount:.6f} {settings.token_currency}; "
                f"{face:.6f} is required before the supplier can be paid"
            )

        rec = _update(rec, status=ReceivableStatus.credit_drawn, draw_tx_hash=withdrawal.tx_hash, draw_explorer_url=withdrawal.explorer_url)

        # Payment to supplier
        supplier_tx_hash, supplier_explorer_url = await _pay_supplier(
            rec.supplier, supplier_amount, invoice_id, settings
        )

        # XLS-66 LoanCreate (if enabled)
        loan_id: str | None = None
        if settings.lending_enabled:
            try:
                from . import lending
                loan_result = await lending.loan_create(
                    invoice_id=invoice_id,
                    amount=face,
                    currency=settings.token_currency,
                )
                loan_id = loan_result.loan_id
            except Exception as exc:
                log.warning("XLS-66 LoanCreate failed for %s (non-fatal): %s", invoice_id, exc)

        rec = _update(
            rec,
            status=ReceivableStatus.awaiting_maturity,
            payment_tx_hash=supplier_tx_hash,
            payment_explorer_url=supplier_explorer_url,
            loan_id=loan_id,
            guardrail_trail=guardrail_trail or [],
        )
        store.commit_spend(_agent_address(settings), idempotency_key)

    except Exception:
        store.release_spend(_agent_address(settings), idempotency_key)
        raise

    _emit_audit("receivable_supplier_paid", rec)
    return rec


# ── collect_repayment ─────────────────────────────────────────────────────────

async def collect_repayment(
    invoice_id: str,
    *,
    repayment_tx_hash: str | None = None,
) -> Receivable:
    """Receive buyer repayment and replenish the vault pool.

    In real mode the buyer submits the Payment independently; the agent calls
    this to record receipt and do the VaultDeposit. In mock mode the repayment
    tx hash is synthetic.

    Status: awaiting_maturity → repayment_received → credit_settled → closed
    """
    settings = get_settings()
    if not settings.trade_finance_enabled:
        raise TradeFinanceDisabled("trade_finance_enabled is False")

    rec = _get_by_invoice(invoice_id)
    if rec.status != ReceivableStatus.awaiting_maturity:
        raise InvalidReceivableState(
            f"receivable {invoice_id} is in state {rec.status}; expected awaiting_maturity"
        )

    face = Decimal(rec.amount).quantize(_QUANTIZE, rounding=ROUND_DOWN)

    # Synthetic repayment hash in mock mode
    if repayment_tx_hash is None:
        repayment_tx_hash = xrpl_client.mock_tx_hash("repayment", invoice_id)

    rec = _update(rec, status=ReceivableStatus.repayment_received, repayment_tx_hash=repayment_tx_hash)

    # VaultDeposit: replenish the pool
    effective_vault_id = settings.vault_id
    if not settings.use_mock_xrpl:
        effective_vault_id = vault_tool.require_vault_id(effective_vault_id)
    else:
        effective_vault_id = effective_vault_id or "mock-vault"
    deposit = await vault_tool.deposit(effective_vault_id, float(face))

    # XLS-66 LoanRepay (if this draw used one)
    settle_tx_hash: str | None = deposit.tx_hash
    if settings.lending_enabled and rec.loan_id:
        try:
            from . import lending
            loan_repay = await lending.loan_repay(rec.loan_id, amount=face)
            settle_tx_hash = loan_repay.tx_hash
        except Exception as exc:
            log.warning("XLS-66 LoanRepay failed for %s (non-fatal): %s", invoice_id, exc)

    rec = _update(rec, status=ReceivableStatus.closed, settle_tx_hash=settle_tx_hash)
    _emit_audit("receivable_closed", rec)
    return rec


# ── Getters ───────────────────────────────────────────────────────────────────

def get_receivable(record_id: str) -> Receivable | None:
    return _receivables.get(record_id)


def get_by_invoice(invoice_id: str) -> Receivable | None:
    rid = _by_invoice.get(invoice_id)
    return _receivables.get(rid) if rid else None


def list_receivables() -> list[Receivable]:
    return sorted(_receivables.values(), key=lambda r: r.created_at, reverse=True)


# ── Private helpers ───────────────────────────────────────────────────────────

async def _pay_supplier(
    supplier: str,
    amount: Decimal,
    invoice_id: str,
    settings,
) -> tuple[str, str | None]:
    if settings.use_mock_xrpl:
        tx_hash = xrpl_client.mock_tx_hash("trade_finance_pay", invoice_id)
        return tx_hash, None

    from ..ledger import Ledger
    from xrpl.models.transactions import Payment, Memo
    import json

    ledger = Ledger(settings)
    wallet = ledger.treasury_wallet
    memo_data = json.dumps({"trade_finance_invoice": invoice_id}, separators=(",", ":"))
    tx = Payment(
        account=wallet.address,
        destination=supplier,
        amount=xrpl_client.to_wire_amount(amount, settings.token_currency, settings),
        source_tag=settings.trade_finance_source_tag,
        memos=[Memo(
            memo_type="trade_finance/v1".encode().hex().upper(),
            memo_data=memo_data.encode().hex().upper(),
        )],
    )
    result = await ledger.submit(tx, wallet)
    tx_hash = result["hash"]
    return tx_hash, xrpl_client.explorer_tx_url_for(tx_hash, settings.xrpl_endpoint)


def _agent_address(settings) -> str:
    if settings.use_mock_xrpl or not settings.treasury_wallet_seed:
        return settings.treasury_wallet_address or "rMOCK_TREASURY_0000000000000000000"
    from ..ledger import Ledger
    return Ledger(settings).treasury_wallet.address


def _get_by_invoice(invoice_id: str) -> Receivable:
    rid = _by_invoice.get(invoice_id)
    if rid is None or rid not in _receivables:
        raise ReceivableNotFound(invoice_id)
    return _receivables[rid]


def _store(rec: Receivable) -> None:
    _receivables[rec.id] = rec
    _by_invoice[rec.invoice_id] = rec.id


def _update(rec: Receivable, **kwargs) -> Receivable:
    kwargs["updated_at"] = datetime.now(timezone.utc)
    # guardrail_trail needs special handling (list → must be set, not merged)
    updated = rec.model_copy(update=kwargs)
    _store(updated)
    _schedule_persist(updated)
    return updated


def _emit_audit(event_type: str, rec: Receivable) -> None:
    from . import audit_log
    audit_log.append(
        event_type=event_type,
        actor="settlement_layer",
        context_kind="loan_underwrite",
        payload={
            "receivable_id": rec.id,
            "invoice_id": rec.invoice_id,
            "status": rec.status.value,
            "amount": rec.amount,
            "discount_rate": rec.discount_rate,
            "payment_tx_hash": rec.payment_tx_hash,
            "settle_tx_hash": rec.settle_tx_hash,
            "loan_id": rec.loan_id,
        },
    )


def _schedule_persist(rec: Receivable) -> None:
    import asyncio
    try:
        asyncio.get_running_loop()
        asyncio.create_task(_persist_receivable(rec))
        return
    except RuntimeError:
        pass


async def _persist_receivable(rec: Receivable) -> None:
    if db.session_factory is None:
        return
    from ..models import ReceivableRecord
    try:
        async with db.session_factory() as session:
            row = ReceivableRecord(
                id=rec.id,
                invoice_id=rec.invoice_id,
                buyer=rec.buyer,
                supplier=rec.supplier,
                amount=rec.amount,
                discount_rate=rec.discount_rate,
                due_date=rec.due_date,
                status=rec.status.value,
                draw_tx_hash=rec.draw_tx_hash,
                draw_explorer_url=rec.draw_explorer_url,
                payment_tx_hash=rec.payment_tx_hash,
                payment_explorer_url=rec.payment_explorer_url,
                repayment_tx_hash=rec.repayment_tx_hash,
                settle_tx_hash=rec.settle_tx_hash,
                loan_id=rec.loan_id,
                guardrail_trail=[g.model_dump() for g in rec.guardrail_trail] if rec.guardrail_trail else None,
                audit_event_id=rec.audit_event_id,
                idempotency_key=f"trade_finance:{rec.invoice_id}",
                created_at=rec.created_at,
                updated_at=rec.updated_at,
            )
            await session.merge(row)
            await session.commit()
    except Exception as exc:
        log.warning("Failed to persist receivable %s: %s", rec.id, exc)


# ── Errors ────────────────────────────────────────────────────────────────────

class TradeFinanceError(Exception):
    pass

class TradeFinanceDisabled(TradeFinanceError):
    pass

class ReceivableNotFound(TradeFinanceError):
    pass

class InvalidReceivableState(TradeFinanceError):
    pass

class InsufficientVaultLiquidity(TradeFinanceError):
    pass
