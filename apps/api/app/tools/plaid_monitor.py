"""Plaid Monitor — AML/PEP/sanctions watchlist screening.

Wraps the Plaid Watchlist Screening API for both individuals and entities.
When credentials and a watchlist program ID are configured this replaces the
OpenSanctions screen inside check_compliance(); otherwise the caller falls back
to OpenSanctions or the demo list.

API docs: https://plaid.com/docs/monitor/

Plaid Monitor screens against 150+ global lists including:
  - OFAC SDN, EU Consolidated, UN Consolidated
  - PEP databases (domestic and foreign)
  - Adverse media

Endpoints used:
  POST /watchlist_screening/individual/create  (ReceiverEntityType.individual)
  POST /watchlist_screening/entity/create      (ReceiverEntityType.company)

The watchlist_program_id must be created in the Plaid Dashboard under Monitor
before calling these endpoints. Leave PLAID_WATCHLIST_PROGRAM_ID_INDIVIDUAL /
PLAID_WATCHLIST_PROGRAM_ID_ENTITY blank to skip Plaid and fall back to
OpenSanctions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

_BASE_URLS = {
    "sandbox": "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production": "https://production.plaid.com",
}

# Hit types that constitute a hard sanctions block
_BLOCKING_HIT_TYPES = {"sanction"}

# Hit types that raise risk but don't block on their own
_PEP_HIT_TYPES = {"pep", "pep_class_1", "pep_class_2", "pep_class_3", "pep_class_4"}

# Adverse media raises AML score but is never a hard block
_ADVERSE_MEDIA_TYPES = {
    "adverse_media",
    "adverse_media_v2_financial_crime",
    "adverse_media_v2_fraud_linked",
    "adverse_media_v2_narcotics_aml_cft",
    "adverse_media_v2_cybercrime",
    "adverse_media_v2_general",
}


@dataclass
class PlaidHit:
    id: str
    review_status: str   # "confirmed_positive" | "dismissed" | "pending_review"
    hit_type: str        # "sanction" | "pep" | "adverse_media" | ...
    name: str
    source_list: str


@dataclass
class PlaidScreeningResult:
    screening_id: str
    status: str                              # "cleared" | "pending_review" | "rejected"
    sanctioned: bool
    is_pep: bool
    has_adverse_media: bool
    hits: list[PlaidHit] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    raw_status: str = ""


def screen_individual(
    *,
    client_id: str,
    secret: str,
    plaid_env: str,
    program_id: str,
    legal_name: str,
    country: str,
    client_user_id: str,
) -> PlaidScreeningResult:
    """Screen an individual against global watchlists via Plaid Monitor."""
    base_url = _BASE_URLS.get(plaid_env, _BASE_URLS["sandbox"])
    payload = {
        "client_id": client_id,
        "secret": secret,
        "search_terms": {
            "watchlist_program_id": program_id,
            "legal_name": legal_name,
            "country": country or None,
        },
        "client_user_id": client_user_id,
    }
    # Remove None values — Plaid rejects null optional fields
    payload["search_terms"] = {k: v for k, v in payload["search_terms"].items() if v is not None}

    with httpx.Client(timeout=15.0) as client:
        response = client.post(f"{base_url}/watchlist_screening/individual/create", json=payload)
        response.raise_for_status()
        data = response.json()

    return _parse_response(data)


def screen_entity(
    *,
    client_id: str,
    secret: str,
    plaid_env: str,
    program_id: str,
    entity_name: str,
    country: str,
    client_user_id: str,
) -> PlaidScreeningResult:
    """Screen a company/entity against global watchlists via Plaid Monitor."""
    base_url = _BASE_URLS.get(plaid_env, _BASE_URLS["sandbox"])
    payload = {
        "client_id": client_id,
        "secret": secret,
        "search_terms": {
            "watchlist_program_id": program_id,
            "legal_name": entity_name,
            "country": country or None,
        },
        "client_user_id": client_user_id,
    }
    payload["search_terms"] = {k: v for k, v in payload["search_terms"].items() if v is not None}

    with httpx.Client(timeout=15.0) as client:
        response = client.post(f"{base_url}/watchlist_screening/entity/create", json=payload)
        response.raise_for_status()
        data = response.json()

    return _parse_response(data)


def _parse_response(data: dict) -> PlaidScreeningResult:
    """Parse a Plaid watchlist screening response into a PlaidScreeningResult."""
    screening_id = data.get("id", "")
    status = data.get("status", "")
    hits_raw = data.get("hits", [])

    hits: list[PlaidHit] = []
    for h in hits_raw:
        review_status = h.get("review_status", "")
        if review_status == "dismissed":
            continue  # analyst-dismissed hits don't count

        listing = h.get("listing", {})
        hit_type = listing.get("type", "unknown")
        name = listing.get("name", "") or (
            f"{listing.get('first_name', '')} {listing.get('last_name', '')}".strip()
        )
        source = listing.get("source", {})
        source_list = source.get("name", "") if isinstance(source, dict) else str(source)

        hits.append(PlaidHit(
            id=h.get("id", ""),
            review_status=review_status,
            hit_type=hit_type,
            name=name,
            source_list=source_list,
        ))

    sanctioned = any(h.hit_type in _BLOCKING_HIT_TYPES for h in hits)
    is_pep = any(h.hit_type in _PEP_HIT_TYPES for h in hits)
    has_adverse_media = any(h.hit_type in _ADVERSE_MEDIA_TYPES for h in hits)

    flags: list[str] = []
    if sanctioned:
        sources = ", ".join({h.source_list for h in hits if h.hit_type in _BLOCKING_HIT_TYPES})
        flags.append(f"Plaid Monitor: sanctions hit ({sources})")
    if is_pep:
        pep_names = ", ".join({h.name for h in hits if h.hit_type in _PEP_HIT_TYPES})
        flags.append(f"Plaid Monitor: PEP match ({pep_names})")
    if has_adverse_media:
        media_types = ", ".join({h.hit_type for h in hits if h.hit_type in _ADVERSE_MEDIA_TYPES})
        flags.append(f"Plaid Monitor: adverse media ({media_types})")

    return PlaidScreeningResult(
        screening_id=screening_id,
        status=status,
        sanctioned=sanctioned,
        is_pep=is_pep,
        has_adverse_media=has_adverse_media,
        hits=hits,
        flags=flags,
        raw_status=status,
    )
