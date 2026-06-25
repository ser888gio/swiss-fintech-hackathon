"""KYA credential URI — Know Your Agent identity encoding.

The XRPL Credential URI field (≤ 256 bytes) carries the agent's identity claim:
  - agent_type : role (orchestrator, sub_agent, monitor, api_gateway)
  - principal  : controlling XRPL address (the org that owns this agent)
  - scopes     : list of authorized action domains
  - issued_on  : ISO date (YYYY-MM-DD)
  - ref        : optional session / deployment reference

Format: compact JSON with short keys, version v=2 (v=1 = KYC steps).
Target size: < 200 bytes for a typical agent credential.

This mirrors kyc/uri.py (KYC) so compliance can cross-check both
credential types from the same URI-decoding path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class AgentType(str, Enum):
    orchestrator = "orchestrator"  # top-level payment orchestrator
    sub_agent = "sub_agent"  # delegated sub-agent
    monitor = "monitor"  # compliance / audit monitor (read-only)
    api_gateway = "api_gateway"  # external API integration agent
    unknown = "unknown"


class AgentScope(str, Enum):
    payment = "payment"  # initiate / route payments
    x402 = "x402"  # pay-at-need (x402 protocol)
    delegation = "delegation"  # grant sub-agent delegations
    compliance = "compliance"  # run compliance screens
    credential_issue = "cred_issue"  # issue KYC / KYA credentials
    read_only = "read_only"  # query only, no writes


@dataclass
class AgentIdentity:
    """Agent identity decoded from a KYA credential URI."""

    agent_type: AgentType = AgentType.unknown
    principal: str = ""  # controlling XRPL address
    scopes: list[AgentScope] = field(default_factory=list)
    ref: str = ""
    issued_on: str = ""

    # ── Scope helpers ─────────────────────────────────────────────────────────

    def has_scope(self, scope: AgentScope) -> bool:
        return scope in self.scopes

    def can_pay(self) -> bool:
        return self.has_scope(AgentScope.payment)

    def can_delegate(self) -> bool:
        return self.has_scope(AgentScope.delegation)

    def can_issue_credentials(self) -> bool:
        return self.has_scope(AgentScope.credential_issue)

    @property
    def scope_summary(self) -> str:
        return ", ".join(s.value for s in self.scopes) if self.scopes else "none"


# ── Short-key codec maps ──────────────────────────────────────────────────────

_SCOPE_SHORT: dict[AgentScope, str] = {
    AgentScope.payment: "pay",
    AgentScope.x402: "x402",
    AgentScope.delegation: "del",
    AgentScope.compliance: "cmp",
    AgentScope.credential_issue: "ci",
    AgentScope.read_only: "ro",
}
_SCOPE_FROM_SHORT: dict[str, AgentScope] = {v: k for k, v in _SCOPE_SHORT.items()}

_TYPE_SHORT: dict[AgentType, str] = {
    AgentType.orchestrator: "orch",
    AgentType.sub_agent: "sub",
    AgentType.monitor: "mon",
    AgentType.api_gateway: "apigw",
    AgentType.unknown: "unk",
}
_TYPE_FROM_SHORT: dict[str, AgentType] = {v: k for k, v in _TYPE_SHORT.items()}


# ── Encoder / decoder ─────────────────────────────────────────────────────────


def build_kya_uri(identity: AgentIdentity) -> str:
    """Encode an AgentIdentity as a compact JSON string for the Credential URI field.

    Targets well under the 256-byte XRPL limit.
    """
    payload: dict = {"v": 2}  # v=2 → KYA  (v=1 → KYC steps)
    if identity.agent_type != AgentType.unknown:
        payload["t"] = _TYPE_SHORT.get(identity.agent_type, identity.agent_type.value)
    if identity.principal:
        payload["p"] = identity.principal
    if identity.scopes:
        payload["s"] = [_SCOPE_SHORT.get(sc, sc.value) for sc in identity.scopes]
    if identity.ref:
        payload["ref"] = identity.ref
    if identity.issued_on:
        payload["iss"] = identity.issued_on
    return json.dumps(payload, separators=(",", ":"))


def parse_kya_uri(uri: str | None) -> AgentIdentity | None:
    """Decode a KYA credential URI. Returns None on any parse or version error."""
    if not uri:
        return None
    try:
        data = json.loads(uri)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("v") != 2:
        return None

    agent_type = _TYPE_FROM_SHORT.get(data.get("t", ""), AgentType.unknown)

    scopes: list[AgentScope] = []
    for raw in data.get("s", []):
        scope = _SCOPE_FROM_SHORT.get(raw)
        if scope is not None:
            scopes.append(scope)

    return AgentIdentity(
        agent_type=agent_type,
        principal=data.get("p", ""),
        scopes=scopes,
        ref=data.get("ref", ""),
        issued_on=data.get("iss", ""),
    )


# ── Convenience constructors ──────────────────────────────────────────────────


def orchestrator_identity(*, principal: str, ref: str = "") -> AgentIdentity:
    """Full-scope orchestrator: pay, delegate, x402, compliance, credential issuance."""
    return AgentIdentity(
        agent_type=AgentType.orchestrator,
        principal=principal,
        scopes=[
            AgentScope.payment,
            AgentScope.x402,
            AgentScope.delegation,
            AgentScope.compliance,
            AgentScope.credential_issue,
        ],
        ref=ref,
        issued_on=date.today().isoformat(),
    )


def sub_agent_identity(
    *,
    principal: str,
    scopes: list[AgentScope],
    ref: str = "",
) -> AgentIdentity:
    """Limited-scope sub-agent: caller specifies exactly which scopes apply."""
    return AgentIdentity(
        agent_type=AgentType.sub_agent,
        principal=principal,
        scopes=scopes,
        ref=ref,
        issued_on=date.today().isoformat(),
    )


def monitor_identity(*, principal: str, ref: str = "") -> AgentIdentity:
    """Read-only monitor: compliance and read_only only."""
    return AgentIdentity(
        agent_type=AgentType.monitor,
        principal=principal,
        scopes=[AgentScope.compliance, AgentScope.read_only],
        ref=ref,
        issued_on=date.today().isoformat(),
    )
