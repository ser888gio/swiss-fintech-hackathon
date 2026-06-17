"""Compliance tool: check_compliance.

Screens the receiver with OpenSanctions when configured, falls back to the demo
screen when not, and combines deterministic risk signals into a single AML
score. Sanctions can block payments; public intelligence can only raise risk.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import get_settings
from ..schemas import (
    ComplianceResult,
    CredentialStatus,
    PaymentIntent,
    ReceiverEntityType,
    SanctionsMatch,
)
from . import public_intel

# Demo sanctions list. Used for local demos and as a graceful provider fallback.
SANCTIONED_ACCOUNTS = {"rSANCTIONED000000000000000000000000", "ACME-SHELL-CO"}
SANCTIONED_NAMES = {"acme shell co", "blocked industries ltd"}
HIGH_RISK_COUNTRIES = {"IR", "KP", "RU", "SY"}
HIGH_RISK_KEYWORDS = ("crypto-mixer", "shell", "unverified")

OPENSANCTIONS_ENTITY_URL = "https://www.opensanctions.org/entities/{id}/"

# Floor applied when KYC credentials are required but the receiver lacks a valid
# one. Set above the default policy flag score so an un-KYC'd counterparty is
# escalated to hardware approval rather than auto-settled — the decision still
# belongs to the policy engine, this only supplies the risk signal.
KYC_MISSING_SCORE = 65


def check_compliance(
    intent: PaymentIntent, credential: CredentialStatus | None = None
) -> ComplianceResult:
    settings = get_settings()
    flags: list[str] = []

    public = public_intel.assess_public_intel(intent)
    matches: list[SanctionsMatch] = []
    sanctioned = False

    if settings.opensanctions_api_key:
        try:
            matches = _screen_opensanctions(intent)
            sanctioned = _has_blocking_match(matches, settings.opensanctions_match_threshold)
        except (httpx.HTTPError, ValueError):
            sanctioned = _fallback_sanctioned(intent)
            flags.append("OpenSanctions unavailable; used local demo sanctions fallback")
    else:
        sanctioned = _fallback_sanctioned(intent)

    if sanctioned:
        flags.append("counterparty on sanctions list")

    if intent.receiver_country.upper() in HIGH_RISK_COUNTRIES:
        flags.append(f"receiver country is high risk ({intent.receiver_country.upper()})")

    reference = f"{intent.reference} {intent.purpose}".lower()
    for keyword in HIGH_RISK_KEYWORDS:
        if keyword in reference:
            flags.append(f"reference mentions '{keyword}'")

    flags.extend(public.flags)

    kyc_missing = credential is not None and credential.checked and not credential.verified
    if kyc_missing:
        flags.append(f"no valid on-chain KYC credential ({credential.reason})")

    score = _score(sanctioned, len(flags), intent.amount, public.score)
    if kyc_missing:
        score = min(max(score, KYC_MISSING_SCORE), 95 if not sanctioned else 100)
    explanation = _explain(score, flags, matches, public.summary)
    return ComplianceResult(
        aml_score=score,
        sanctioned=sanctioned,
        flags=flags,
        explanation=explanation,
        sanctions_matches=matches,
        public_intel=public,
        credential=credential,
    )


def build_opensanctions_request(intent: PaymentIntent) -> dict[str, Any]:
    schema = "Person" if intent.receiver_entity_type is ReceiverEntityType.individual else "Company"
    properties: dict[str, list[str]] = {
        "name": [intent.receiver_name],
        "country": [intent.receiver_country],
    }
    return {
        "queries": {
            "receiver": {
                "schema": schema,
                "properties": properties,
            }
        }
    }


def _screen_opensanctions(intent: PaymentIntent) -> list[SanctionsMatch]:
    settings = get_settings()
    base_url = settings.opensanctions_base_url.rstrip("/")
    dataset = settings.opensanctions_dataset.strip("/") or "sanctions"
    headers = {"Authorization": f"ApiKey {settings.opensanctions_api_key}"}
    with httpx.Client(timeout=10.0, headers=headers) as client:
        response = client.post(
            f"{base_url}/match/{dataset}",
            json=build_opensanctions_request(intent),
        )
        response.raise_for_status()
        payload = response.json()
    return _parse_matches(payload)


def _parse_matches(payload: dict[str, Any]) -> list[SanctionsMatch]:
    response = payload.get("responses", {}).get("receiver", {})
    results = response.get("results", [])
    matches: list[SanctionsMatch] = []
    for result in results:
        entity_id = str(result.get("id") or "")
        if not entity_id:
            continue
        matches.append(
            SanctionsMatch(
                id=entity_id,
                caption=str(result.get("caption") or entity_id),
                schema_=str(result.get("schema") or ""),
                score=float(result.get("score") or 0.0),
                datasets=[str(item) for item in result.get("datasets", [])],
                url=OPENSANCTIONS_ENTITY_URL.format(id=entity_id),
            )
        )
    return matches


def _has_blocking_match(matches: list[SanctionsMatch], threshold: float) -> bool:
    return any(match.score >= threshold for match in matches)


def _fallback_sanctioned(intent: PaymentIntent) -> bool:
    return is_sanctioned(intent.to, intent.receiver_name)


def is_sanctioned(address: str, name: str | None = None) -> bool:
    """Deterministic sanctions check for a single counterparty (address + name).

    Used by the credential-issuing agent to refuse issuing a KYC credential to a
    sanctioned subject. Code decides — never the LLM. Uses the local demo list;
    swap for the OpenSanctions screen when a key is configured.
    """
    if address in SANCTIONED_ACCOUNTS:
        return True
    if name and name.strip().lower() in SANCTIONED_NAMES:
        return True
    return False


def _score(sanctioned: bool, flag_count: int, amount: float, public_intel_score: int) -> int:
    if sanctioned:
        return 100
    score = 10 + flag_count * 25
    if amount >= 25_000:
        score += 10
    score = max(score, public_intel_score)
    return min(score, 95)


def _explain(
    score: int,
    flags: list[str],
    matches: list[SanctionsMatch],
    public_intel_summary: str,
) -> str:
    parts: list[str] = []
    if flags:
        parts.append(f"AML score {score}/100. Flags: {'; '.join(flags)}.")
    else:
        parts.append(f"Clean screen. AML score {score}/100, no flags raised.")

    if matches:
        top = max(matches, key=lambda match: match.score)
        parts.append(f"Top OpenSanctions match: {top.caption} ({top.score:.2f}).")

    if public_intel_summary:
        parts.append(public_intel_summary)

    return " ".join(parts)
