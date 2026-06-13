"""In-memory payment store for the demo skeleton.

Swap for the SQLAlchemy models in app/models.py + a Postgres session when
persistence is needed (see docs/architecture.md). The route layer depends only
on these functions, so the swap is local.
"""

from __future__ import annotations

from .schemas import AgentLogEntry, Payment

_payments: dict[str, Payment] = {}
_logs: list[AgentLogEntry] = []


def save(payment: Payment) -> Payment:
    _payments[payment.id] = payment
    return payment


def get(payment_id: str) -> Payment | None:
    return _payments.get(payment_id)


def list_payments() -> list[Payment]:
    return sorted(_payments.values(), key=lambda p: p.created_at, reverse=True)


def append_log(entry: AgentLogEntry) -> None:
    _logs.append(entry)


def logs_for(payment_id: str) -> list[AgentLogEntry]:
    return [entry for entry in _logs if entry.payment_id == payment_id]
