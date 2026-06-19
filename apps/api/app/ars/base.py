"""Agentic Risk Standard (ARS) abstract base classes — XRPL realization.

These ABCs define the contracts that every ARS role must satisfy. Concrete
implementations swap network config (Devnet → Mainnet) without changing callers.
The three classes map to the ARS settlement-layer ABC surface:

  SettlementLayer  — RLUSD Payment / TokenEscrow (XLS-85) submit+confirm
  FeeEscrow        — per-job fee locked on-ledger, released on delivery verdict
  CollateralVault  — agent collateral (slash on default, release on pass)

ConstraintEngine wraps the existing policy/engine.py + scope.py guardrail chain
so every ARS role (payment, loan underwrite, insurance payout) calls the same
deterministic gate, distinguished by `context_kind`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal


ContextKind = Literal["payment", "loan_underwrite", "insurance_payout", "delegation_fund"]


@dataclass(frozen=True)
class ConstraintResult:
    """Outcome of a single constraint-engine evaluation."""

    allowed: bool
    action: Literal["allow", "review", "block"]
    rule_fired: str | None
    reasons: list[str]
    # Ordered trail: each guardrail and whether it passed.
    guardrail_trail: list["GuardrailOutcome"]


@dataclass(frozen=True)
class GuardrailOutcome:
    name: str          # e.g. "G1_kya", "G4_scope"
    passed: bool
    rule_fired: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class SettlementReceipt:
    tx_hash: str
    explorer_url: str | None
    network: str           # "mock" | "testnet" | "devnet" | "mainnet"
    amount: Decimal
    currency: str


@dataclass(frozen=True)
class EscrowReceipt:
    escrow_sequence: int
    create_tx_hash: str
    explorer_url: str | None
    network: str
    amount: Decimal
    currency: str


class ConstraintEngine(ABC):
    """ARS constraint engine — the guardrail gate every ARS role uses.

    `evaluate` is deterministic and pure within an async context: it reads
    the guardrail inputs (passed in by the caller, which fetches them from the
    store + reservation table atomically), runs G1–G7 in order, and returns
    a ConstraintResult. The LLM never calls this; only deterministic code does.
    """

    @abstractmethod
    async def evaluate(
        self,
        *,
        context_kind: ContextKind,
        agent_address: str,
        counterparty: str | None,
        amount: Decimal,
        currency: str,
        aml_score: int,
        sanctioned: bool,
        agent_credential_verified: bool,
        spent_today: Decimal,
        scope_max_per_tx: Decimal,
        scope_max_per_day: Decimal,
        allowed_service_hosts: list[str] | None = None,
        service_host: str | None = None,
        delegation_budget_remaining: Decimal | None = None,
    ) -> ConstraintResult:
        ...


class SettlementLayer(ABC):
    """ARS settlement layer — submit a signed RLUSD Payment to XRPL."""

    @abstractmethod
    async def settle(
        self,
        *,
        from_address: str,
        to_address: str,
        amount: Decimal,
        currency: str,
        memo_data: dict | None = None,
        source_tag: int | None = None,
        invoice_id: str | None = None,
    ) -> SettlementReceipt:
        ...

    @abstractmethod
    async def lock(
        self,
        *,
        from_address: str,
        to_address: str,
        amount: Decimal,
        currency: str,
        finish_after: int,
        memo_data: dict | None = None,
        source_tag: int | None = None,
    ) -> EscrowReceipt:
        ...

    @abstractmethod
    async def finish_escrow(self, *, escrow_sequence: int) -> SettlementReceipt:
        ...


class FeeEscrow(ABC):
    """ARS fee track — lock job fee on-ledger, release on delivery verdict."""

    @abstractmethod
    async def lock_fee(
        self,
        *,
        job_id: str,
        payer: str,
        payee: str,
        amount: Decimal,
        currency: str,
    ) -> EscrowReceipt:
        ...

    @abstractmethod
    async def release_fee(self, *, job_id: str, escrow_sequence: int) -> SettlementReceipt:
        ...

    @abstractmethod
    async def cancel_fee(self, *, job_id: str, escrow_sequence: int) -> SettlementReceipt:
        ...


class CollateralVault(ABC):
    """ARS principal track — agent collateral: slash on default, release on pass."""

    @abstractmethod
    async def post_collateral(
        self,
        *,
        agent_address: str,
        job_id: str,
        amount: Decimal,
        currency: str,
    ) -> EscrowReceipt:
        ...

    @abstractmethod
    async def release_collateral(
        self, *, job_id: str, escrow_sequence: int
    ) -> SettlementReceipt:
        ...

    @abstractmethod
    async def slash(
        self,
        *,
        job_id: str,
        escrow_sequence: int,
        merchant: str,
        amount: Decimal,
    ) -> SettlementReceipt:
        ...
