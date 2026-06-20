"""AML risk model — deterministic, weighted, typology-tagged.

Implements FATF-aligned risk signals without any external API calls. Each
check returns a RiskSignal carrying a typology code, a weight (points added
to the AML score), a short flag string, and an audit-grade evidence sentence.

The compliance tool assembles signals into a score; the policy engine acts on
that score. No I/O anywhere here — all inputs are passed in by the caller.

Typology codes follow FATF/FINCEN naming conventions so audit reports can
reference internationally recognised categories.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AMLTypology(str, Enum):
    jurisdiction = "JRSD"   # high-risk country or corridor
    structuring  = "STRC"   # amount just below a reporting threshold
    layering     = "LAYR"   # round-number or repetitive-amount pattern
    shell_entity = "SHLL"   # opaque / shell-company name indicators
    pep_exposure = "PEPE"   # politically exposed person signals
    documentation = "DOCQ"  # vague purpose or missing reference
    velocity     = "VELC"   # repeated payments to the same counterparty


@dataclass(frozen=True)
class RiskSignal:
    typology: AMLTypology
    weight: int    # points added to the AML score (base is 10)
    flag: str      # short text added to ComplianceResult.flags
    evidence: str  # longer detail written to the audit trail


# ── Country risk tiers (FATF-aligned, 2025) ──────────────────────────────────

# "Call for Action" — highest risk, subject to countermeasures
FATF_BLACKLIST: frozenset[str] = frozenset({"IR", "KP", "MM"})

# "Increased Monitoring" — greylist, active deficiencies identified
FATF_GREYLIST: frozenset[str] = frozenset({
    "AF", "BF", "CM", "CD", "HT", "JM", "ML", "MZ", "NG",
    "PH", "SN", "SS", "SY", "TZ", "VN", "YE", "ZA",
})

# Major sanctions regimes (OFAC/EU/UN) — heightened correspondent risk
SANCTIONS_JURISDICTIONS: frozenset[str] = frozenset({
    "RU", "BY", "CU", "VE", "ZW", "SD", "LY",
})

# Secrecy / low-disclosure jurisdictions — elevated shell-entity risk
SECRECY_JURISDICTIONS: frozenset[str] = frozenset({
    "VG", "KY", "BZ", "PA", "SC", "WS", "VU", "NR",
})

# ── Shell entity name tokens ──────────────────────────────────────────────────

# Strong indicators — high confidence alone
_SHELL_STRONG: frozenset[str] = frozenset({
    "shell", "offshore", "nominee", "bearer",
})

# Soft indicators — suspicious in combination or with high-risk country
_SHELL_SOFT: frozenset[str] = frozenset({
    "holdings", "ventures", "capital", "international",
    "global", "enterprises", "solutions", "group", "partners",
    "associates", "consultants", "resources", "management",
    "properties", "investments", "trading", "trust",
})

# ── PEP title tokens ─────────────────────────────────────────────────────────

_PEP_TITLES: frozenset[str] = frozenset({
    "minister", "senator", "governor", "president", "chairman",
    "ambassador", "consul", "judge", "general", "admiral",
    "secretary", "treasurer", "commissioner",
})

# ── Vague purpose strings ─────────────────────────────────────────────────────

_VAGUE_PURPOSES: frozenset[str] = frozenset({
    "payment", "transfer", "funds", "money", "transaction",
    "remittance", "fee", "service", "business", "general",
    "other", "n/a", "na", "none", "misc", "miscellaneous",
    "various", "see invoice", "as agreed", "per agreement",
    "invoice", "wire", "wired",
})


def evaluate_signals(
    *,
    receiver_name: str,
    receiver_country: str,
    sender_country: str,
    receiver_entity_type: str,   # "individual" | "company"
    amount: float,
    currency: str,
    purpose: str,
    reference: str,
    policy_threshold: float = 10_000.0,
    prior_payment_count: int = 0,    # settled/released payments to same receiver in last 24h
    prior_payment_total: float = 0.0,
) -> list[RiskSignal]:
    """Evaluate all AML signals for a payment intent.

    Pure function — no I/O. All inputs must be supplied by the caller (which
    fetches velocity counts from the store before calling this).

    Returns a list of RiskSignal objects ordered by typology. An empty list
    means no signals fired; the base AML score will be 10.
    """
    signals: list[RiskSignal] = []
    rc  = receiver_country.upper()
    sc  = sender_country.upper()
    name_lower  = receiver_name.strip().lower()
    name_tokens = set(name_lower.split())
    purpose_lower   = purpose.strip().lower()
    reference_lower = reference.strip().lower()

    # ── G1: Jurisdictional risk ───────────────────────────────────────────────

    if rc in FATF_BLACKLIST:
        signals.append(RiskSignal(
            typology=AMLTypology.jurisdiction,
            weight=35,
            flag=f"receiver country {rc} is on the FATF blacklist (Call for Action)",
            evidence=(
                f"FATF has placed {rc} under its highest-risk category requiring "
                "countermeasures. Correspondent transactions carry extreme regulatory exposure."
            ),
        ))
    elif rc in FATF_GREYLIST:
        signals.append(RiskSignal(
            typology=AMLTypology.jurisdiction,
            weight=20,
            flag=f"receiver country {rc} is on the FATF increased-monitoring list",
            evidence=(
                f"FATF has {rc} under increased monitoring for identified AML/CFT deficiencies. "
                "Enhanced due diligence is required per FATF Recommendation 10."
            ),
        ))
    elif rc in SANCTIONS_JURISDICTIONS:
        signals.append(RiskSignal(
            typology=AMLTypology.jurisdiction,
            weight=25,
            flag=f"receiver country {rc} is subject to major sanctions regimes",
            evidence=(
                f"{rc} is subject to OFAC, EU, and/or UN sanctions. "
                "Payments may constitute a sanctions violation; legal review required."
            ),
        ))

    if rc in SECRECY_JURISDICTIONS:
        signals.append(RiskSignal(
            typology=AMLTypology.jurisdiction,
            weight=12,
            flag=f"receiver country {rc} is a low-disclosure secrecy jurisdiction",
            evidence=(
                f"{rc} has limited beneficial ownership transparency and restricted "
                "regulatory access. Shell and nominee structures are common."
            ),
        ))

    if sc in FATF_BLACKLIST | FATF_GREYLIST | SANCTIONS_JURISDICTIONS:
        signals.append(RiskSignal(
            typology=AMLTypology.jurisdiction,
            weight=15,
            flag=f"sender country {sc} is a high-risk jurisdiction",
            evidence=(
                f"Payment originates from {sc}, itself a high-risk jurisdiction. "
                "Both ends of a corridor must be assessed per FATF Recommendation 13."
            ),
        ))

    # ── G2: Structuring detection ─────────────────────────────────────────────
    # Only apply to currencies where we know the policy threshold is meaningful.
    # Cross-currency amounts are compared heuristically against the threshold.
    if policy_threshold > 0:
        ratio = amount / policy_threshold
        if 0.80 <= ratio < 1.0:
            signals.append(RiskSignal(
                typology=AMLTypology.structuring,
                weight=30,
                flag=(
                    f"amount {amount:,.2f} {currency} is {ratio * 100:.0f}% of the "
                    f"{policy_threshold:,.0f} approval threshold — possible structuring"
                ),
                evidence=(
                    f"Amount falls within 20% below the {policy_threshold:,.0f} threshold. "
                    "Structuring (smurfing) to avoid reporting triggers is a primary AML "
                    "typology catalogued under FATF Recommendation 1."
                ),
            ))

    # ── G3: Round-number layering ─────────────────────────────────────────────
    if amount >= 1_000:
        for multiple in (10_000, 5_000, 1_000):
            if amount % multiple == 0:
                signals.append(RiskSignal(
                    typology=AMLTypology.layering,
                    weight=12,
                    flag=f"exact round-number amount ({amount:,.0f} {currency}) — layering indicator",
                    evidence=(
                        f"Payment is an exact multiple of {multiple:,}. Legitimate invoices "
                        "rarely produce perfectly round figures; this pattern is associated "
                        "with layering in the FINCEN typologies library."
                    ),
                ))
                break  # fire once for the largest matching multiple

    # ── G4: Shell entity name analysis ───────────────────────────────────────

    strong_hits = name_tokens & _SHELL_STRONG
    soft_hits   = name_tokens & _SHELL_SOFT

    if strong_hits:
        signals.append(RiskSignal(
            typology=AMLTypology.shell_entity,
            weight=30,
            flag=f"receiver name contains high-confidence shell indicator: '{', '.join(sorted(strong_hits))}'",
            evidence=(
                f"Name '{receiver_name}' contains a term strongly associated with nominee "
                "or shell structures. Beneficial ownership verification is required."
            ),
        ))
    elif len(soft_hits) >= 2:
        signals.append(RiskSignal(
            typology=AMLTypology.shell_entity,
            weight=18,
            flag=f"receiver name has multiple opacity indicators: '{', '.join(sorted(soft_hits))}'",
            evidence=(
                f"Name '{receiver_name}' contains {len(soft_hits)} generic corporate tokens "
                "with no identifying specificity. Common pattern in layering structures."
            ),
        ))
    elif soft_hits and receiver_entity_type == "company":
        high_risk_country = rc in (FATF_BLACKLIST | FATF_GREYLIST | SANCTIONS_JURISDICTIONS | SECRECY_JURISDICTIONS)
        if high_risk_country:
            signals.append(RiskSignal(
                typology=AMLTypology.shell_entity,
                weight=15,
                flag=f"corporate receiver in high-risk jurisdiction with generic naming ('{', '.join(sorted(soft_hits))}')",
                evidence=(
                    f"Company '{receiver_name}' in {rc} uses generic nomenclature "
                    "typical of shell vehicles. Combined with jurisdictional risk, "
                    "this warrants enhanced due diligence."
                ),
            ))

    # ── G5: PEP exposure ─────────────────────────────────────────────────────

    pep_hits = {t for t in _PEP_TITLES if t in name_lower}
    if pep_hits:
        signals.append(RiskSignal(
            typology=AMLTypology.pep_exposure,
            weight=25,
            flag=f"receiver name suggests a politically exposed person ({', '.join(sorted(pep_hits))})",
            evidence=(
                f"Name '{receiver_name}' contains a PEP title indicator. "
                "PEPs require enhanced due diligence and senior management approval "
                "per FATF Recommendation 12."
            ),
        ))

    # ── G6: Documentation quality ─────────────────────────────────────────────

    purpose_is_vague = (
        purpose_lower in _VAGUE_PURPOSES
        or len(purpose_lower) < 4
        or purpose_lower.replace(" ", "").replace("_", "") in {
            v.replace(" ", "") for v in _VAGUE_PURPOSES
        }
    )
    if purpose_is_vague:
        signals.append(RiskSignal(
            typology=AMLTypology.documentation,
            weight=15,
            flag=f"vague payment purpose: '{purpose}'",
            evidence=(
                "The purpose field provides insufficient information about the economic "
                "rationale. FATF Recommendation 16 requires genuine transaction purpose "
                "documentation for wire transfers."
            ),
        ))

    reference_is_missing = (
        len(reference_lower.strip()) < 3
        or reference_lower in ("n/a", "na", "none", "-", ".", "ref", "tbd")
    )
    if reference_is_missing:
        signals.append(RiskSignal(
            typology=AMLTypology.documentation,
            weight=8,
            flag="missing or placeholder payment reference",
            evidence=(
                "A blank or placeholder reference reduces traceability and makes "
                "post-settlement reconciliation and audit harder."
            ),
        ))

    # ── G7: Payment velocity ─────────────────────────────────────────────────

    if prior_payment_count >= 3:
        signals.append(RiskSignal(
            typology=AMLTypology.velocity,
            weight=20,
            flag=(
                f"{prior_payment_count} prior payments to this receiver in 24h "
                f"(total {prior_payment_total:,.2f}) — velocity alert"
            ),
            evidence=(
                f"High payment frequency to a single counterparty ({prior_payment_count} "
                f"transactions, {prior_payment_total:,.2f} total in 24h) is consistent "
                "with rapid cycling / layering (FINCEN advisory FIN-2014-A005)."
            ),
        ))
    elif prior_payment_count >= 1:
        signals.append(RiskSignal(
            typology=AMLTypology.velocity,
            weight=8,
            flag=f"repeated payment to this receiver ({prior_payment_count + 1} in 24h)",
            evidence=(
                f"This is payment #{prior_payment_count + 1} to {receiver_name} "
                "within a 24-hour window."
            ),
        ))

    return signals


def signals_to_score(
    signals: list[RiskSignal],
    sanctioned: bool,
    public_intel_score: int,
) -> int:
    """Aggregate signals into a single AML score (0–100).

    Base is 10 (innocent until proven suspicious). Sanction always pins to 100.
    Public intel can only raise the score, never lower it.
    """
    if sanctioned:
        return 100
    score = 10 + sum(s.weight for s in signals)
    score = max(score, public_intel_score)
    return min(score, 95)


def signals_by_typology(signals: list[RiskSignal]) -> dict[str, list[RiskSignal]]:
    """Group signals by typology code — useful for structured audit output."""
    result: dict[str, list[RiskSignal]] = {}
    for s in signals:
        result.setdefault(s.typology.value, []).append(s)
    return result
