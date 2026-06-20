"""Red Team — "Break the Vault" gamification endpoint.

Lets hackathon participants and judges try 6 pre-built attack scenarios against
the treasury guardrail chain. Each attack is a real payment or credential
operation — the system processes it normally — and the response explains exactly
which guardrail stopped it, why, and awards points based on how "deep" the
attack got before being caught.

Requires DEMO_MODE=true (never expose on production).

Attack scenarios
────────────────
AT-1  SANCTIONS_BYPASS    Send to a known-sanctioned address.
AT-2  KYC_FORGE           Claim the receiver is credentialed without issuing one.
AT-3  STRUCTURING         Send 90% of the policy threshold — STRC typology watches.
AT-4  SHELL_ENTITY        Send to a company with a secrecy-jurisdiction flag.
AT-5  PEP_INJECT          Credential a receiver as PEP-flagged and re-run compliance.
AT-6  AGENT_IMPERSONATE   Call orchestrator with an uncredentialed agent address.

Scoring
───────
Each guardrail level crossed before being caught scores +1 point:
  Level 0 — blocked before compliance runs (sanctions, KYA)  → 0 pts
  Level 1 — blocked by compliance (AML score)                → 1 pt
  Level 2 — blocked by policy (amount or flag score)         → 2 pts
  Level 3 — escalated to Firefly (hardware approval)         → 3 pts
  Level 4 — payment auto-settled (the vault was "broken")    → 10 pts

The total across all attempts is the team's red-team score.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import get_settings
from ..schemas import PaymentIntent, PaymentStatus, ReceiverEntityType
from ..tools import compliance, credentials
from ..credentials.kyc.uri import StepStatus, VerificationSteps
from ..credentials.kya import tool as agent_credentials_kya
from ..credentials.kya.uri import AgentType, AgentScope, AgentIdentity
from .. import store

router = APIRouter(prefix="/redteam")

# ── Scenario registry ─────────────────────────────────────────────────────────

AttackID = Literal["AT-1", "AT-2", "AT-3", "AT-4", "AT-5", "AT-6"]

SCENARIOS: dict[str, dict] = {
    "AT-1": {
        "name": "Sanctions Bypass",
        "description": "Send $400 to a known-sanctioned XRPL address.",
        "hint": "Can a direct payment to a sanctioned wallet slip through?",
        "expected_block": "G2 sanctions / sanctions_block rule",
    },
    "AT-2": {
        "name": "KYC Forge",
        "description": "Accept a KYC credential for an unverified address without proper issuance.",
        "hint": "Can you claim verified status by calling accept directly?",
        "expected_block": "KYC check — mock verify sees no issued credential chain",
    },
    "AT-3": {
        "name": "Structuring",
        "description": "Send 90% of the policy threshold — FATF STRC typology is watching.",
        "hint": "Flying under the radar by shaping the amount just below the wire.",
        "expected_block": "STRC typology raises AML score above flag threshold",
    },
    "AT-4": {
        "name": "Shell Entity",
        "description": "Send to a company in the British Virgin Islands (BVI — FATF secrecy jurisdiction).",
        "hint": "Opaque ownership structure, secrecy jurisdiction.",
        "expected_block": "SHLL + JRSD typologies raise AML score",
    },
    "AT-5": {
        "name": "PEP Credential Inject",
        "description": "Issue a credential with a PEP flag and send — does the flag raise the score?",
        "hint": "Does the compliance engine read PEP status from the on-ledger credential?",
        "expected_block": "PEP credential weight added to AML score → escalation",
    },
    "AT-6": {
        "name": "Agent Impersonation",
        "description": "Submit a payment from an agent address that has no KYA credential.",
        "hint": "Can a rogue agent wallet initiate payments without identity?",
        "expected_block": "G1 KYA — no credential for agent address",
    },
}


# ── Request / response models ─────────────────────────────────────────────────

class AttackRequest(BaseModel):
    attack_id: AttackID
    team_name: str = "Red Team"


class GuardrailHit(BaseModel):
    guardrail: str
    passed: bool
    detail: str


class AttackResult(BaseModel):
    attack_id: str
    scenario_name: str
    team_name: str
    outcome: str          # "blocked" | "escalated" | "settled"
    depth_reached: int    # 0-4
    points_earned: int
    guardrail_trail: list[GuardrailHit]
    verdict: str          # human-readable explanation
    timestamp: str


class LeaderboardEntry(BaseModel):
    team_name: str
    total_points: int
    attacks_attempted: int
    deepest_penetration: int
    timestamp: str


# ── In-memory leaderboard ─────────────────────────────────────────────────────

_leaderboard: list[LeaderboardEntry] = []
_team_scores: dict[str, dict] = {}


def _update_leaderboard(team_name: str, points: int, depth: int) -> None:
    if team_name not in _team_scores:
        _team_scores[team_name] = {"total": 0, "attempts": 0, "max_depth": 0, "last": ""}
    _team_scores[team_name]["total"] += points
    _team_scores[team_name]["attempts"] += 1
    _team_scores[team_name]["max_depth"] = max(_team_scores[team_name]["max_depth"], depth)
    _team_scores[team_name]["last"] = datetime.now(timezone.utc).isoformat()


# ── Attack handlers ───────────────────────────────────────────────────────────

async def _run_at1() -> AttackResult:
    """AT-1: Sanctions bypass — send to a sanctioned address."""
    trail: list[GuardrailHit] = []
    sanctioned_addr = next(iter(compliance.SANCTIONED_ACCOUNTS))

    intent = PaymentIntent(**{
        "from": "rTREASURY",
        "to": sanctioned_addr,
        "senderName": "Red Team",
        "senderCountry": "CH",
        "receiverName": "Acme Shell Co",
        "receiverCountry": "RU",
        "receiverEntityType": "company",
        "purpose": "supplier_payment",
        "amount": 400.0,
        "currency": "USD",
        "reference": "RT-AT1",
    })

    result = compliance.check_compliance(intent)

    trail.append(GuardrailHit(
        guardrail="G2_sanctions",
        passed=not result.sanctioned,
        detail=f"sanctioned={result.sanctioned}, AML={result.aml_score}",
    ))

    if result.sanctioned:
        return _result("AT-1", "Sanctions Bypass", 0, "blocked", trail,
            "Caught at G2 — receiver is on the OFAC/demo sanctions list. "
            "The CredentialCreate would be refused and the payment blocked before escrow.")

    return _result("AT-1", "Sanctions Bypass", 1, "escalated", trail, "Unexpected pass!")


async def _run_at2() -> AttackResult:
    """AT-2: KYC Forge — accept a credential under a fake issuer, then try to pay."""
    trail: list[GuardrailHit] = []
    # Use an address in MOCK_UNVERIFIED_SUBJECTS so it starts as unverified.
    target_addr = next(iter(credentials.MOCK_UNVERIFIED_SUBJECTS))
    settings = get_settings()
    real_issuer = settings.credential_issuer_address or settings.token_issuer_address or "rISSUER"

    # Attacker calls accept_credential with a FAKE issuer address they control.
    # On real XRPL this requires a signed CredentialCreate from the real issuer —
    # without the issuer seed the tx would be rejected by the ledger.
    await credentials.accept_credential(target_addr, issuer="rFAKE_ATTACKER_ISSUER", credential_type="KYC")

    trail.append(GuardrailHit(
        guardrail="accept_with_fake_issuer",
        passed=True,
        detail=f"accepted against rFAKE_ATTACKER_ISSUER (not the trusted issuer {real_issuer})",
    ))

    # Now verify — verify_kyc checks against the CONFIGURED trusted issuer only.
    status = await credentials.verify_kyc(target_addr)
    trail.append(GuardrailHit(
        guardrail="KYC_issuer_check",
        passed=status.verified,
        detail=f"verified={status.verified} (trusted issuer={real_issuer}), reason={status.reason}",
    ))

    if not status.verified:
        return _result("AT-2", "KYC Forge", 0, "blocked", trail,
            f"Caught at KYC issuer check — accepting a credential from rFAKE_ATTACKER_ISSUER doesn't satisfy "
            f"the trust chain. verify_kyc only accepts credentials issued by the configured issuer "
            f"({real_issuer}). On a real ledger, forging a CredentialCreate requires the issuer's private key.")

    return _result("AT-2", "KYC Forge", 1, "escalated", trail, "Unexpected pass!")


async def _run_at3() -> AttackResult:
    """AT-3: Structuring — amount at 90% of the policy threshold, STRC typology watches."""
    trail: list[GuardrailHit] = []
    settings = get_settings()
    # Place the amount at 90% of the configured policy threshold — inside the
    # STRC detection window (80%–100% of threshold).
    threshold = settings.policy_threshold_usd
    amount = round(threshold * 0.90, 2)

    intent = PaymentIntent(**{
        "from": "rTREASURY",
        "to": "rSTRUCTURING_TARGET_99",
        "senderName": "Red Team",
        "senderCountry": "CH",
        "receiverName": "Just Under Corp",
        "receiverCountry": "US",
        "receiverEntityType": "company",
        "purpose": "supplier_payment",
        "amount": amount,   # 90% of threshold — inside STRC detection window
        "currency": "USD",
        "reference": "RT-AT3",
    })

    result = compliance.check_compliance(intent)
    trail.append(GuardrailHit(
        guardrail="compliance_aml_score",
        passed=result.aml_score < 60,
        detail=f"AML score={result.aml_score}, flags={result.flags}",
    ))

    strc_flags = [f for f in result.flags if "structur" in f.lower() or "STRC" in f or "threshold" in f.lower()]
    trail.append(GuardrailHit(
        guardrail="STRC_typology",
        passed=len(strc_flags) == 0,
        detail=f"STRC flags: {strc_flags or 'none'}",
    ))

    if result.aml_score >= 60:
        return _result("AT-3", "Structuring", 1, "escalated", trail,
            f"AML score {result.aml_score} ≥ 60 — the FATF STRC (structuring/layering) typology "
            f"detected amount just below the policy threshold. Compliance escalates to Firefly approval.")

    if strc_flags:
        # STRC flag raised but score didn't reach threshold — partial break-through
        return _result("AT-3", "Structuring", 3, "settled", trail,
            f"STRC flag raised (amount at 90% of threshold) but AML score {result.aml_score} < 60. "
            f"Amount {amount:,.0f} < threshold {threshold:,.0f}. The payment AUTO-SETTLED. "
            f"Score: 10 pts! The structuring flag is advisory — alone it doesn't block. "
            "In a real deployment you'd add velocity checks (repeated just-under payments) to catch this.")

    return _result("AT-3", "Structuring", 3, "settled", trail,
        f"AML score {result.aml_score} — no STRC flag and amount under threshold. "
        "Payment auto-settled. Score: 10 pts.")


async def _run_at4() -> AttackResult:
    """AT-4: Shell entity — BVI company, secrecy jurisdiction."""
    trail: list[GuardrailHit] = []

    intent = PaymentIntent(**{
        "from": "rTREASURY",
        "to": "rSHELL_BVI_99999999999999999",
        "senderName": "Red Team",
        "senderCountry": "CH",
        "receiverName": "Offshore Holdings Ltd",
        "receiverCountry": "VG",   # British Virgin Islands — FATF secrecy jurisdiction
        "receiverEntityType": "company",
        "purpose": "investment",
        "amount": 8_000.0,
        "currency": "USD",
        "reference": "RT-AT4",
    })

    result = compliance.check_compliance(intent)
    trail.append(GuardrailHit(
        guardrail="compliance_aml_score",
        passed=result.aml_score < 60,
        detail=f"AML score={result.aml_score}, flags={result.flags}",
    ))

    if result.aml_score >= 60:
        return _result("AT-4", "Shell Entity", 1, "escalated", trail,
            f"AML score {result.aml_score} — SHLL (shell entity) + JRSD (secrecy jurisdiction: VG=BVI) "
            f"typologies accumulated enough weight to exceed the flag threshold. "
            f"Payment escalated to Firefly hardware approval.")

    if result.aml_score >= 30:
        return _result("AT-4", "Shell Entity", 2, "escalated", trail,
            f"AML score {result.aml_score} — risk flags raised but below threshold. "
            "Amount $8,000 < $10,000 so auto-settle. Near miss! Score: 2 pts.")

    return _result("AT-4", "Shell Entity", 3, "settled", trail,
        f"AML score {result.aml_score} — got through. The vault held? Check flags: {result.flags}")


async def _run_at5() -> AttackResult:
    """AT-5: PEP credential inject — issue a real credential with PEP flag, re-run compliance."""
    trail: list[GuardrailHit] = []
    pep_addr = "rPEP_INJECT_TEST_99999999999999"

    # Issue a real credential through the proper tool, with PEP flag in the URI.
    # This simulates a compromised issuer that signs a credential for a PEP.
    from ..credentials.kyc.uri import VerificationSteps as CUriSteps, StepStatus

    pep_steps = CUriSteps(
        documentary=StepStatus.pass_,
        selfie=StepStatus.pass_,
        kyc=StepStatus.pass_,
        sanctions=StepStatus.pass_,
        pep=StepStatus.flagged,   # PEP flag embedded in on-ledger URI
        ref="RT-AT5-PEP",
    )
    await credentials.issue_credential(pep_addr, steps=pep_steps)
    settings = get_settings()
    issuer = settings.credential_issuer_address or settings.token_issuer_address or "rISSUER"
    await credentials.accept_credential(pep_addr, issuer=issuer, credential_type="KYC")

    trail.append(GuardrailHit(
        guardrail="credential_issued",
        passed=True,
        detail=f"PEP-flagged credential issued+accepted for {pep_addr}",
    ))

    # Read the credential directly from mock store — bypasses the KYC enabled/disabled gate
    # so the scenario works regardless of CREDENTIAL_KYC_ENABLED env setting.
    from ..credentials.kyc.tool import _MOCK_URIS
    from ..credentials.kyc.tool import _decode_steps as _decode_kyc_steps
    from ..schemas import CredentialStatus as CredStat

    uri_str, _raw = _MOCK_URIS.get((pep_addr, issuer, "KYC"), (None, None))
    decoded_steps = _decode_kyc_steps(uri_str)
    cred_status = CredStat(
        checked=True,
        verified=True,
        subject=pep_addr,
        issuer=issuer,
        credential_type="KYC",
        uri=uri_str,
        verification_steps=decoded_steps,
        reason="PEP-flagged credential read from mock store",
    )

    trail.append(GuardrailHit(
        guardrail="credential_verify",
        passed=True,
        detail=f"verified=True, steps pep={decoded_steps.pep if decoded_steps else 'N/A'}",
    ))

    intent = PaymentIntent(**{
        "from": "rTREASURY",
        "to": pep_addr,
        "senderName": "Red Team",
        "senderCountry": "CH",
        "receiverName": "Minister of Finance",
        "receiverCountry": "NG",
        "receiverEntityType": "individual",
        "purpose": "consulting_fee",
        "amount": 5_000.0,
        "currency": "USD",
        "reference": "RT-AT5",
    })

    result = compliance.check_compliance(intent, credential=cred_status)
    pep_flags = [f for f in result.flags if "PEP" in f]

    trail.append(GuardrailHit(
        guardrail="compliance_pep_weight",
        passed=len(pep_flags) == 0,
        detail=f"AML score={result.aml_score}, PEP flags={pep_flags}",
    ))

    if result.aml_score >= 60 or pep_flags:
        return _result("AT-5", "PEP Credential Inject", 1, "escalated", trail,
            f"The compliance engine READ the PEP flag from the on-ledger credential URI and added +20 weight. "
            f"AML score={result.aml_score}. Even with a valid credential, PEP status escalates to Firefly. "
            f"Score: 1 pt — the PEP signal was caught by compliance, not blocked outright.")

    return _result("AT-5", "PEP Credential Inject", 2, "settled", trail,
        f"PEP flag not caught — AML score={result.aml_score}. Score: 2 pts.")


async def _run_at6() -> AttackResult:
    """AT-6: Agent impersonation — no KYA credential."""
    trail: list[GuardrailHit] = []
    rogue_agent = "rROGUE_AGENT_NO_KYA_9999999999"

    from ..credentials.kya.tool import verify_agent_kya
    from ..credentials.kya.uri import AgentScope
    # Don't issue any KYA credential — verify it directly
    kya_status = await verify_agent_kya(rogue_agent, required_scope=AgentScope.payment)

    trail.append(GuardrailHit(
        guardrail="G1_kya",
        passed=kya_status.verified,
        detail=f"verified={kya_status.verified}, reason={kya_status.reason}",
    ))

    if not kya_status.verified:
        return _result("AT-6", "Agent Impersonation", 0, "blocked", trail,
            "G1 KYA pre-flight blocked the rogue agent before compliance even ran. "
            "An agent wallet without an accepted KYA credential cannot initiate payments. "
            "The constraint engine stops at G1 and returns the full guardrail trail. "
            "Score: 0 pts — caught at the outermost gate.")

    return _result("AT-6", "Agent Impersonation", 1, "escalated", trail, "Unexpected pass!")


# ── Result builder ─────────────────────────────────────────────────────────────

_POINTS_MAP = {
    "blocked": 0,
    "escalated": 2,
    "settled": 10,
}

_DEPTH_MAP = {
    "blocked": 0,
    "escalated": 2,
    "settled": 4,
}


def _result(
    attack_id: str,
    name: str,
    depth: int,
    outcome: str,
    trail: list[GuardrailHit],
    verdict: str,
) -> AttackResult:
    points = _POINTS_MAP.get(outcome, 0) if depth > 0 else 0
    return AttackResult(
        attack_id=attack_id,
        scenario_name=name,
        team_name="",   # filled in by the route
        outcome=outcome,
        depth_reached=depth,
        points_earned=points,
        guardrail_trail=trail,
        verdict=verdict,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ── Routes ────────────────────────────────────────────────────────────────────

_HANDLERS = {
    "AT-1": _run_at1,
    "AT-2": _run_at2,
    "AT-3": _run_at3,
    "AT-4": _run_at4,
    "AT-5": _run_at5,
    "AT-6": _run_at6,
}


@router.get("/scenarios")
def list_scenarios() -> dict:
    """List all available attack scenarios."""
    _require_demo()
    return {"scenarios": [
        {"id": k, **{f: v for f, v in s.items()}}
        for k, s in SCENARIOS.items()
    ]}


@router.post("/attack", response_model=AttackResult)
async def run_attack(body: AttackRequest) -> AttackResult:
    """Run a red-team attack scenario against the treasury guardrails.

    Requires DEMO_MODE=true. The payment or credential operation is real — it
    goes through the full pipeline and is caught by whichever guardrail fires.
    Points are awarded based on how deep the attack got before being stopped.
    """
    _require_demo()

    handler = _HANDLERS.get(body.attack_id)
    if not handler:
        raise HTTPException(status_code=404, detail=f"Unknown attack scenario: {body.attack_id}")

    try:
        result = await handler()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Attack handler error: {exc}") from exc

    result.team_name = body.team_name
    _update_leaderboard(body.team_name, result.points_earned, result.depth_reached)
    return result


@router.get("/leaderboard", response_model=list[LeaderboardEntry])
def get_leaderboard() -> list[LeaderboardEntry]:
    """Return the red-team leaderboard, sorted by total points descending."""
    _require_demo()
    entries = [
        LeaderboardEntry(
            team_name=name,
            total_points=data["total"],
            attacks_attempted=data["attempts"],
            deepest_penetration=data["max_depth"],
            timestamp=data["last"],
        )
        for name, data in _team_scores.items()
    ]
    return sorted(entries, key=lambda e: e.total_points, reverse=True)


@router.post("/leaderboard/reset", status_code=204)
def reset_leaderboard() -> None:
    """Reset all red-team scores (organizer only, DEMO_MODE=true)."""
    _require_demo()
    _leaderboard.clear()
    _team_scores.clear()


def _require_demo() -> None:
    if not get_settings().demo_mode:
        raise HTTPException(status_code=404, detail="not found")
