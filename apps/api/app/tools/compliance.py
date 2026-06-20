"""Compliance tool: check_compliance.

Screens the receiver with OpenSanctions when configured, falls back to the demo
screen when not, and assembles deterministic risk signals into a single AML
score using the FATF-aligned risk model in tools/risk_model.py.

Sanctions can block payments outright. All other signals feed the AML score
which the policy engine compares against its flag threshold to decide whether
to escalate to hardware approval.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ..config import get_settings
from ..schemas import (
    ComplianceResult,
    CredentialStatus,
    PaymentIntent,
    PaymentStatus,
    ReceiverEntityType,
    SanctionsMatch,
)
from . import country_risk, public_intel, risk_model
from ..credentials.plaid import monitor as plaid_monitor

# Demo sanctions list. Used for local demos and as a graceful provider fallback.
SANCTIONED_ACCOUNTS = {"rSANCTIONED000000000000000000000000", "ACME-SHELL-CO"}
SANCTIONED_NAMES = {"acme shell co", "blocked industries ltd"}

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

    # ── 1. External OSINT (advisory, score only raises) ───────────────────────
    public = public_intel.assess_public_intel(intent)
    geopolitical = country_risk.assess_country_risk(intent, settings)

    # ── 2. Sanctions / PEP screening ─────────────────────────────────────────
    matches: list[SanctionsMatch] = []
    sanctioned = False
    is_pep = False
    has_adverse_media = False
    fallback_used = False
    sanctions_basis: list[str] = []
    plaid_flags: list[str] = []

    plaid_result = _screen_plaid(intent, settings)
    if plaid_result is not None:
        sanctioned = plaid_result.sanctioned
        is_pep = plaid_result.is_pep
        has_adverse_media = plaid_result.has_adverse_media
        plaid_flags = plaid_result.flags
        if sanctioned:
            sanctions_basis.append("Plaid Monitor entity match")
    elif settings.opensanctions_api_key:
        try:
            matches = _screen_opensanctions(intent)
            sanctioned = _has_blocking_match(matches, settings.opensanctions_match_threshold)
            if sanctioned:
                sanctions_basis.append("OpenSanctions entity match")
        except (httpx.HTTPError, ValueError):
            sanctioned = _fallback_sanctioned(intent)
            fallback_used = True
    else:
        sanctioned = _fallback_sanctioned(intent)
        if sanctioned:
            sanctions_basis.append("local demo entity match")

    if sanctioned and not sanctions_basis:
        sanctions_basis.append("local demo entity match")

    if geopolitical.blocked:
        sanctioned = True
        sanctions_basis.append("country sanctions / geopolitical policy")

    # ── 3. Velocity check from payment store ──────────────────────────────────
    prior_count, prior_total = _velocity_check(intent)

    # ── 4. FATF-aligned AML signal evaluation ─────────────────────────────────
    signals = risk_model.evaluate_signals(
        receiver_name=intent.receiver_name,
        receiver_country=intent.receiver_country,
        sender_country=intent.sender_country,
        receiver_entity_type=intent.receiver_entity_type.value,
        amount=intent.amount,
        currency=intent.currency,
        purpose=intent.purpose,
        reference=intent.reference,
        policy_threshold=getattr(settings, "policy_threshold_usd", 10_000.0),
        prior_payment_count=prior_count,
        prior_payment_total=prior_total,
    )

    # ── 5. Assemble flags ─────────────────────────────────────────────────────
    flags: list[str] = []
    step_weight = 0  # default; overwritten below if credential has steps

    if sanctioned:
        flags.append("counterparty on sanctions list")
    flags.extend(geopolitical.reasons)
    if fallback_used:
        flags.append("OpenSanctions unavailable; used local demo sanctions fallback")

    # Plaid Monitor flags (sanctions, PEP, adverse media)
    flags.extend(plaid_flags)

    # Flags from the risk model signals
    flags.extend(s.flag for s in signals)

    # Promote Plaid PEP / adverse-media signals into the risk model score
    # by injecting synthetic signals so the weight is applied consistently.
    if is_pep and not any(s.typology == risk_model.AMLTypology.pep_exposure for s in signals):
        signals = list(signals) + [risk_model.RiskSignal(
            typology=risk_model.AMLTypology.pep_exposure,
            weight=25,
            flag="Plaid Monitor confirmed PEP match",
            evidence="Plaid Monitor returned a PEP hit for this counterparty.",
        )]
    if has_adverse_media:
        signals = list(signals) + [risk_model.RiskSignal(
            typology=risk_model.AMLTypology.pep_exposure,
            weight=15,
            flag="Plaid Monitor adverse media signal",
            evidence="Plaid Monitor flagged adverse media associated with this counterparty.",
        )]

    # Public intel flags
    flags.extend(public.flags)

    # KYC credential status + per-step signals
    kyc_missing = credential is not None and credential.checked and not credential.verified
    if kyc_missing:
        flags.append(f"no valid on-chain KYC credential ({credential.reason})")

    # Step-level signals from the credential URI (Plaid-modelled verification manifest)
    step_weight = 0
    if credential is not None and credential.verified and credential.verification_steps:
        vsteps = credential.verification_steps
        step_flags = _step_flags(vsteps)
        flags.extend(step_flags)
        step_weight = _step_weight(vsteps)

    # ── 6. Score ──────────────────────────────────────────────────────────────
    score = risk_model.signals_to_score(signals, sanctioned, public.score)
    score = min(score + step_weight, 95) if not sanctioned else score

    if not sanctioned:
        score = max(score, geopolitical.score)
        if fallback_used:
            score = max(
                score,
                getattr(settings, "sanctions_unavailable_review_score", 65),
            )

    if kyc_missing:
        score = min(max(score, KYC_MISSING_SCORE), 95 if not sanctioned else 100)

    # ── 7. Explanation ────────────────────────────────────────────────────────
    explanation = _explain(score, flags, matches, signals, public.summary, geopolitical)

    return ComplianceResult(
        aml_score=score,
        sanctioned=sanctioned,
        flags=flags,
        explanation=explanation,
        sanctions_matches=matches,
        sanctions_basis=sanctions_basis,
        geopolitical_risk=geopolitical,
        public_intel=public,
        credential=credential,
    )


# ── OpenSanctions integration ─────────────────────────────────────────────────

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


# ── Plaid Monitor screening ───────────────────────────────────────────────────

def _screen_plaid(
    intent: PaymentIntent, settings
) -> "plaid_monitor.PlaidScreeningResult | None":
    """Call Plaid Monitor if credentials and a program ID are configured.

    Returns None when Plaid is not configured so the caller falls through to
    OpenSanctions. HTTP errors are caught and logged as a flag; the caller
    then falls back to OpenSanctions/demo list.
    """
    client_id = getattr(settings, "plaid_client_id", "")
    secret = getattr(settings, "plaid_secret", "")
    if not (client_id and secret):
        return None

    is_individual = intent.receiver_entity_type == ReceiverEntityType.individual
    program_id = (
        getattr(settings, "plaid_watchlist_program_id_individual", "")
        if is_individual
        else getattr(settings, "plaid_watchlist_program_id_entity", "")
    )
    if not program_id:
        return None

    plaid_env = getattr(settings, "plaid_env", "sandbox")

    try:
        if is_individual:
            return plaid_monitor.screen_individual(
                client_id=client_id,
                secret=secret,
                plaid_env=plaid_env,
                program_id=program_id,
                legal_name=intent.receiver_name,
                country=intent.receiver_country,
                client_user_id=intent.to,
            )
        else:
            return plaid_monitor.screen_entity(
                client_id=client_id,
                secret=secret,
                plaid_env=plaid_env,
                program_id=program_id,
                entity_name=intent.receiver_name,
                country=intent.receiver_country,
                client_user_id=intent.to,
            )
    except httpx.HTTPError as exc:
        # Plaid unavailable — caller falls through to OpenSanctions
        import logging
        logging.getLogger(__name__).warning("Plaid Monitor unavailable: %s", exc)
        return None


# ── Velocity check ────────────────────────────────────────────────────────────

def _velocity_check(intent: PaymentIntent) -> tuple[int, float]:
    """Count recent payments to the same receiver from the in-memory store.

    Returns (count, total_amount) for settled/released/pending payments to
    intent.to within the last 24 hours. Blocked payments are excluded because
    they never moved funds. Pure read — no side effects.
    """
    try:
        from .. import store

        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        non_terminal_statuses = {
            PaymentStatus.settled,
            PaymentStatus.released,
            PaymentStatus.pending_approval,
            PaymentStatus.routing,
        }
        recent = [
            p for p in store.list_payments()
            if p.intent.to == intent.to
            and p.status in non_terminal_statuses
            and p.created_at >= cutoff
        ]
        total = sum(p.intent.amount for p in recent)
        return len(recent), total
    except Exception:
        # Store not available (test context without DB). Treat as no history.
        return 0, 0.0


# ── Explanation builder ───────────────────────────────────────────────────────

def _explain(
    score: int,
    flags: list[str],
    matches: list[SanctionsMatch],
    signals: list[risk_model.RiskSignal],
    public_intel_summary: str,
    geopolitical=None,
) -> str:
    parts: list[str] = []

    if score == 100:
        parts.append(f"BLOCKED. AML score {score}/100 — counterparty is sanctioned.")
    elif flags:
        typologies = sorted({s.typology.value for s in signals})
        typology_str = f" Typologies: {', '.join(typologies)}." if typologies else ""
        parts.append(f"AML score {score}/100.{typology_str} Flags: {'; '.join(flags)}.")
    else:
        parts.append(f"Clean screen. AML score {score}/100, no risk signals fired.")

    if matches:
        top = max(matches, key=lambda m: m.score)
        parts.append(f"Top OpenSanctions match: {top.caption} ({top.score:.2f}).")

    if geopolitical and geopolitical.summary:
        parts.append(f"Geopolitical context: {geopolitical.summary}")

    if public_intel_summary:
        parts.append(public_intel_summary)

    return " ".join(parts)


# ── Credential step helpers ───────────────────────────────────────────────────

def _step_flags(vsteps) -> list[str]:
    """Derive compliance flags from credential verification steps."""
    from ..schemas import VerificationStepStatus as S
    flags: list[str] = []
    if vsteps.documentary == S.fail:
        flags.append("credential: government ID scan failed at issuance")
    if vsteps.selfie == S.fail:
        flags.append("credential: liveness check failed at issuance")
    if vsteps.kyc == S.fail:
        flags.append("credential: name/DOB verification failed at issuance")
    if vsteps.sanctions == S.flagged:
        flags.append("credential: sanctions hit recorded at time of KYC issuance")
    if vsteps.pep == S.flagged:
        flags.append("credential: counterparty confirmed PEP at time of KYC issuance")
    if vsteps.documentary == S.skip:
        flags.append("credential: documentary step not performed — identity not document-verified")
    if vsteps.sanctions == S.skip:
        flags.append("credential: sanctions screen not recorded in credential URI")
    return flags


def _step_weight(vsteps) -> int:
    """AML score contribution from credential step outcomes."""
    from ..schemas import VerificationStepStatus as S
    weight = 0
    if vsteps.pep == S.flagged:
        weight += 20
    if vsteps.sanctions == S.flagged:
        weight += 30
    if vsteps.documentary == S.fail or vsteps.selfie == S.fail or vsteps.kyc == S.fail:
        weight += 15
    # Verified identity slightly offsets generic risk signals
    if vsteps.documentary == S.pass_ and vsteps.selfie == S.pass_:
        weight -= 5
    if vsteps.sanctions == S.pass_:
        weight -= 5
    return max(weight, 0)
