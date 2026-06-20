"""Credential URI builder and parser — Plaid-modelled verification steps.

XRPL Credentials (XLS-70) carry an optional URI field (up to 256 bytes, stored
as hex on-ledger). We use this field to encode a structured verification manifest
that mirrors Plaid IDV's per-step outcomes:

  Plaid IDV step       →  our URI key
  ─────────────────────────────────────
  documentary          →  doc        (government ID scanned and authenticated)
  selfie_check         →  selfie     (liveness confirmed, face matches ID)
  kyc_check            →  kyc        (name/DOB cross-referenced against records)
  sanctions_check      →  sanctions  (screened against OFAC/EU/UN lists)
  pep_check            →  pep        (politically exposed person check)

URI format (compact JSON, max ~200 chars):
  {"v":1,"doc":"pass","selfie":"pass","kyc":"pass","sanctions":"pass","pep":"clear","ref":"abc123","ts":"2026-06-20"}

The compliance tool reads these steps from the decoded URI, so it knows:
  - whether the counterparty's identity was document-verified at issuance
  - whether they were sanctions-screened when the credential was issued
  - whether they are a PEP (requiring enhanced due diligence)
  - when and by whom the checks were run (via ref + ts)

This gives the audit trail depth equivalent to a Plaid Monitor + IDV report,
anchored on-chain and cryptographically bound to the counterparty's address.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timezone, datetime
from enum import Enum


class StepStatus(str, Enum):
    pass_   = "pass"       # step completed, no issues found
    fail    = "fail"       # step completed, verification failed
    flagged = "flagged"    # completed, issues found (PEP / adverse media)
    skip    = "skip"       # step not performed (optional step omitted)
    pending = "pending"    # not yet completed


@dataclass
class VerificationSteps:
    """Per-step KYC verification outcomes — mirrors Plaid IDV step schema.

    All steps default to skip (not performed). Issuers set only the steps
    they actually ran, leaving the rest as skip. The compliance tool treats
    skip differently from fail — a skipped step is unknown, a failed step
    is a risk signal.
    """
    documentary: StepStatus = StepStatus.skip   # government ID scan
    selfie: StepStatus      = StepStatus.skip   # liveness / face match
    kyc: StepStatus         = StepStatus.skip   # name/DOB/address check
    sanctions: StepStatus   = StepStatus.skip   # sanctions list screening
    pep: StepStatus         = StepStatus.skip   # PEP check

    # Issuer reference (e.g. the KYC provider's case ID or report ID)
    ref: str = ""
    # ISO date when the credential was issued
    issued_on: str = ""

    @property
    def identity_verified(self) -> bool:
        """True when both documentary and selfie steps passed."""
        return (
            self.documentary == StepStatus.pass_
            and self.selfie == StepStatus.pass_
        )

    @property
    def sanctions_cleared(self) -> bool:
        """True when a sanctions screen was run and returned clean."""
        return self.sanctions == StepStatus.pass_

    @property
    def is_pep(self) -> bool:
        """True when the PEP check returned a match."""
        return self.pep == StepStatus.flagged

    @property
    def has_failures(self) -> bool:
        """True when any step that was run came back as fail."""
        return any(
            s == StepStatus.fail
            for s in (self.documentary, self.selfie, self.kyc, self.sanctions)
        )

    def risk_flags(self) -> list[str]:
        """Return compliance flags derived from step outcomes."""
        flags: list[str] = []
        if self.documentary == StepStatus.fail:
            flags.append("credential: government ID scan failed at issuance")
        if self.selfie == StepStatus.fail:
            flags.append("credential: liveness check failed at issuance")
        if self.kyc == StepStatus.fail:
            flags.append("credential: name/DOB verification failed at issuance")
        if self.sanctions == StepStatus.flagged:
            flags.append("credential: sanctions hit recorded at issuance")
        if self.pep == StepStatus.flagged:
            flags.append("credential: counterparty is a PEP (flagged at issuance)")
        if self.documentary == StepStatus.skip:
            flags.append("credential: documentary step not performed — identity not document-verified")
        if self.sanctions == StepStatus.skip:
            flags.append("credential: sanctions screen not recorded in credential")
        return flags

    def aml_weight(self) -> int:
        """Score contribution from step outcomes (added on top of base risk signals)."""
        weight = 0
        if self.is_pep:
            weight += 20
        if self.has_failures:
            weight += 15
        if self.sanctions == StepStatus.flagged:
            weight += 30
        # Positive signals: verified identity slightly offsets generic risk
        if self.identity_verified:
            weight -= 5
        if self.sanctions_cleared:
            weight -= 5
        return max(weight, 0)   # never negative contribution


# ── URI encoding / decoding ───────────────────────────────────────────────────

_STEP_KEYS = {
    "documentary": "doc",
    "selfie": "selfie",
    "kyc": "kyc",
    "sanctions": "sanctions",
    "pep": "pep",
}
_STATUS_ALIASES = {
    "pass": StepStatus.pass_,
    "fail": StepStatus.fail,
    "flagged": StepStatus.flagged,
    "skip": StepStatus.skip,
    "pending": StepStatus.pending,
    "clear": StepStatus.pass_,      # Plaid uses "clear" for PEP; map to pass
    "success": StepStatus.pass_,    # Plaid IDV step status alias
    "failed": StepStatus.fail,
}
_URI_VERSION = 1


def build_uri(steps: VerificationSteps) -> str:
    """Encode verification steps as a compact JSON string for the URI field.

    The returned string is stored via xrpl-py's str_to_hex() in the on-ledger
    URI field. Keep it under 200 chars so the hex fits within the 256-byte limit.
    """
    payload: dict = {"v": _URI_VERSION}

    if steps.documentary != StepStatus.skip:
        payload["doc"] = steps.documentary.value
    if steps.selfie != StepStatus.skip:
        payload["selfie"] = steps.selfie.value
    if steps.kyc != StepStatus.skip:
        payload["kyc"] = steps.kyc.value
    if steps.sanctions != StepStatus.skip:
        payload["sanctions"] = steps.sanctions.value
    if steps.pep != StepStatus.skip:
        payload["pep"] = steps.pep.value
    if steps.ref:
        payload["ref"] = steps.ref
    if steps.issued_on:
        payload["ts"] = steps.issued_on
    else:
        payload["ts"] = date.today().isoformat()

    return json.dumps(payload, separators=(",", ":"))


def parse_uri(uri: str | None) -> VerificationSteps | None:
    """Decode a URI string back into VerificationSteps.

    Returns None when the URI is absent or not in our format (e.g. a plain
    https:// URL from an older credential). The compliance tool treats None
    as unknown — not as fail.
    """
    if not uri:
        return None
    uri = uri.strip()

    # Only parse our own structured format
    if not uri.startswith("{"):
        return None

    try:
        data = json.loads(uri)
    except (json.JSONDecodeError, ValueError):
        return None

    if data.get("v") != _URI_VERSION:
        return None

    def _s(key: str) -> StepStatus:
        raw = data.get(key)
        if raw is None:
            return StepStatus.skip
        return _STATUS_ALIASES.get(str(raw).lower(), StepStatus.skip)

    return VerificationSteps(
        documentary=_s("doc"),
        selfie=_s("selfie"),
        kyc=_s("kyc"),
        sanctions=_s("sanctions"),
        pep=_s("pep"),
        ref=str(data.get("ref", "")),
        issued_on=str(data.get("ts", "")),
    )


def full_pass(ref: str = "") -> VerificationSteps:
    """Convenience: all steps passed (use for a fully verified credential)."""
    return VerificationSteps(
        documentary=StepStatus.pass_,
        selfie=StepStatus.pass_,
        kyc=StepStatus.pass_,
        sanctions=StepStatus.pass_,
        pep=StepStatus.pass_,
        ref=ref,
        issued_on=date.today().isoformat(),
    )


def sanctions_only(*, sanctioned: bool = False, is_pep: bool = False, ref: str = "") -> VerificationSteps:
    """Convenience: only sanctions + PEP steps run (no documentary IDV)."""
    return VerificationSteps(
        sanctions=StepStatus.flagged if sanctioned else StepStatus.pass_,
        pep=StepStatus.flagged if is_pep else StepStatus.pass_,
        ref=ref,
        issued_on=date.today().isoformat(),
    )
