"""Deterministic country sanctions and geopolitical-risk policy.

Country policy is configuration owned by compliance operators.  It is kept
separate from entity matching because a person/company match and a territorial
restriction are different pieces of evidence and must remain distinguishable
in the audit trail.

Curated jurisdiction-risk dataset (point-in-time snapshot, 2026-06):
  - Operators extend or override via SANCTIONS_BLOCKED_COUNTRIES /
    GEOPOLITICAL_REVIEW_COUNTRIES env vars (union, not replace).
  - Sources: FATF lists (fatf-gafi.org), EU Annex to Delegated Reg. 2016/1675,
    OFAC comprehensive sanctions programs (ofac.treas.gov).
"""

from __future__ import annotations

from ..config import get_settings
from ..schemas import GeopoliticalRiskResult, PaymentIntent

# ── Curated jurisdiction dataset ─────────────────────────────────────────────
# Each entry: tier ("blocked" | "review"), one-line rationale, citable sources.
# "blocked" → hard block (AML score 100, same as a sanctions hit).
# "review"  → raises AML score → Firefly hardware approval required.

_JURISDICTION_DB: dict[str, dict] = {
    # ── FATF call-for-action ──
    "IR": {
        "tier": "blocked",
        "rationale": "Iran is subject to a FATF call for action and comprehensive OFAC sanctions; no compliant cross-border payment path exists.",
        "sources": ["FATF call for action", "OFAC Iran Sanctions Program"],
    },
    "KP": {
        "tier": "blocked",
        "rationale": "North Korea is subject to a FATF call for action and UN Security Council comprehensive sanctions.",
        "sources": ["FATF call for action", "UN Security Council Sanctions"],
    },
    "MM": {
        "tier": "blocked",
        "rationale": "Myanmar is subject to a FATF call for action following the 2021 military coup; significant financial crime and evasion risks.",
        "sources": ["FATF call for action", "EU Restrictive Measures"],
    },
    # ── OFAC comprehensive sanctions programs ──
    "CU": {
        "tier": "review",
        "rationale": "Cuba is subject to a comprehensive OFAC embargo; transactions require specific OFAC licences.",
        "sources": ["OFAC Cuba Sanctions Program"],
    },
    "SY": {
        "tier": "review",
        "rationale": "Syria is subject to comprehensive OFAC and EU sanctions; enhanced due diligence required.",
        "sources": ["OFAC Syria Sanctions Program", "EU Restrictive Measures"],
    },
    # ── FATF grey-list (increased monitoring) ──
    "PK": {
        "tier": "review",
        "rationale": "Pakistan is on the FATF increased-monitoring list; enhanced due diligence applies to financial flows.",
        "sources": ["FATF increased monitoring"],
    },
    "YE": {
        "tier": "review",
        "rationale": "Yemen is on the FATF increased-monitoring list; ongoing armed conflict raises ML/TF risks.",
        "sources": ["FATF increased monitoring"],
    },
    "LA": {
        "tier": "review",
        "rationale": "Laos is on the FATF increased-monitoring list for strategic AML/CFT deficiencies.",
        "sources": ["FATF increased monitoring"],
    },
    "HT": {
        "tier": "review",
        "rationale": "Haiti is on the FATF increased-monitoring list; weak governance and high corruption risk.",
        "sources": ["FATF increased monitoring"],
    },
    "VU": {
        "tier": "review",
        "rationale": "Vanuatu is on the FATF increased-monitoring list for weak beneficial-ownership controls.",
        "sources": ["FATF increased monitoring"],
    },
    # ── EU high-risk third countries ──
    "AF": {
        "tier": "review",
        "rationale": "Afghanistan is designated an EU high-risk third country for strategic AML/CFT deficiencies.",
        "sources": ["EU high-risk third country", "FATF increased monitoring"],
    },
    "CD": {
        "tier": "review",
        "rationale": "Democratic Republic of the Congo is designated an EU high-risk third country.",
        "sources": ["EU high-risk third country"],
    },
    "SS": {
        "tier": "review",
        "rationale": "South Sudan is designated an EU high-risk third country with significant financial crime risks.",
        "sources": ["EU high-risk third country"],
    },
    "TD": {
        "tier": "review",
        "rationale": "Chad is designated an EU high-risk third country for AML/CFT deficiencies.",
        "sources": ["EU high-risk third country"],
    },
    # ── Broad sectoral sanctions ──
    "RU": {
        "tier": "review",
        "rationale": "Russia is subject to broad EU, UK, and US sectoral sanctions following the 2022 invasion of Ukraine; enhanced due diligence required.",
        "sources": ["EU Restrictive Measures", "OFAC Russia-related Sanctions", "UK Sanctions"],
    },
    "BY": {
        "tier": "review",
        "rationale": "Belarus is subject to EU and US sectoral sanctions; enhanced due diligence required.",
        "sources": ["EU Restrictive Measures", "OFAC Belarus Sanctions"],
    },
    "VE": {
        "tier": "review",
        "rationale": "Venezuela is subject to OFAC sectoral sanctions targeting the oil and financial sectors.",
        "sources": ["OFAC Venezuela Sanctions Program"],
    },
    "ZW": {
        "tier": "review",
        "rationale": "Zimbabwe is subject to targeted EU and US sanctions; governance and corruption risks.",
        "sources": ["OFAC Zimbabwe Sanctions Program", "EU Restrictive Measures"],
    },
}


def assess_country_risk(intent: PaymentIntent, settings=None) -> GeopoliticalRiskResult:
    settings = settings or get_settings()
    country = intent.receiver_country.strip().upper()

    curated = _JURISDICTION_DB.get(country)

    env_blocked = _country_codes(getattr(settings, "sanctions_blocked_countries", ""))
    env_review = _country_codes(getattr(settings, "geopolitical_review_countries", ""))

    is_curated_blocked = curated is not None and curated["tier"] == "blocked"
    is_curated_review = curated is not None and curated["tier"] == "review"

    blocked = is_curated_blocked or country in env_blocked
    review = (is_curated_review or country in env_review) and not blocked

    reasons: list[str] = []
    sources: list[str] = []

    if curated:
        reasons.append(curated["rationale"])
        sources.extend(curated["sources"])

    if blocked and not is_curated_blocked:
        reasons.append(
            f"receiver country {country} is blocked by the configured sanctions policy"
        )
        if "operator_country_policy" not in sources:
            sources.append("operator_country_policy")
    elif review and not is_curated_review:
        reasons.append(
            f"receiver country {country} requires enhanced geopolitical review"
        )
        if "operator_country_policy" not in sources:
            sources.append("operator_country_policy")

    if not sources:
        sources = ["operator_country_policy"]

    if blocked:
        level, score = "blocked", 100
        summary = (
            f"{country} is blocked: {curated['rationale']}"
            if curated
            else f"{country} is blocked by the configured sanctions policy."
        )
    elif review:
        level, score = "high", getattr(settings, "geopolitical_review_score", 65)
        summary = (
            f"{country} requires enhanced geopolitical due diligence: {curated['rationale']}"
            if curated
            else f"{country} requires enhanced geopolitical review per operator policy."
        )
    else:
        level, score = "standard", 0
        summary = ""

    return GeopoliticalRiskResult(
        country=country,
        risk_level=level,
        score=score,
        blocked=blocked,
        requires_review=review and not blocked,
        reasons=reasons,
        sources=sources,
        summary=summary,
    )


def _country_codes(value: str) -> set[str]:
    return {item.strip().upper() for item in value.split(",") if item.strip()}
