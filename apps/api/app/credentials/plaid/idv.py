"""Plaid Identity Verification (IDV) — sender-side KYC.

Creates and retrieves Plaid IDV sessions. The frontend receives a
shareable_url and opens it (modal or redirect) so the sender scans their
government-issued ID and completes a liveness check.

API docs: https://plaid.com/docs/identity-verification/

Flow:
  1. Backend: create_session()  → shareable_url sent to frontend
  2. User:    completes ID scan + selfie in Plaid Link / hosted URL
  3. Backend: get_session()     → returns IDVStatus with verified bool

The verified flag feeds into check_compliance() as a sender KYC signal.
A missing or failed IDV raises the AML score (code decides, not the LLM).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import httpx

_BASE_URLS = {
    "sandbox": "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production": "https://production.plaid.com",
}


class IDVStatus(str, Enum):
    active = "active"  # session created, user has not started
    success = "success"  # all steps passed
    failed = "failed"  # one or more steps failed
    expired = "expired"  # session timed out
    canceled = "canceled"  # user abandoned


@dataclass
class IDVSession:
    session_id: str
    status: IDVStatus
    shareable_url: str | None
    # Step-level outcomes
    documentary_verified: bool  # government ID scan passed
    selfie_verified: bool  # liveness check passed
    # Extracted identity fields (present when status == success)
    given_name: str | None = None
    family_name: str | None = None
    date_of_birth: str | None = None
    country: str | None = None
    # Populated when a step fails
    failure_reasons: list[str] = field(default_factory=list)

    @property
    def verified(self) -> bool:
        return self.status == IDVStatus.success

    @property
    def failed(self) -> bool:
        return self.status == IDVStatus.failed


def create_session(
    *,
    client_id: str,
    secret: str,
    plaid_env: str,
    template_id: str,
    client_user_id: str,
    email: str | None = None,
    given_name: str | None = None,
    family_name: str | None = None,
) -> IDVSession:
    """Create a new Plaid IDV session for a sender.

    Returns an IDVSession with shareable_url — send this URL to the frontend
    so the user can complete their identity check.
    """
    base_url = _BASE_URLS.get(plaid_env, _BASE_URLS["sandbox"])

    user: dict = {"client_user_id": client_user_id}
    if email:
        user["email_address"] = email
    if given_name or family_name:
        user["name"] = {}
        if given_name:
            user["name"]["given_name"] = given_name
        if family_name:
            user["name"]["family_name"] = family_name

    payload = {
        "client_id": client_id,
        "secret": secret,
        "template_id": template_id,
        "gave_consent": True,
        "user": user,
    }

    with httpx.Client(timeout=15.0) as client:
        response = client.post(
            f"{base_url}/identity_verification/create",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    return _parse_session(data)


def get_session(
    *,
    client_id: str,
    secret: str,
    plaid_env: str,
    session_id: str,
) -> IDVSession:
    """Retrieve the current state of an IDV session.

    Call this to poll for completion after the user has been sent to the
    shareable_url. Returns an IDVSession with verified=True when done.
    """
    base_url = _BASE_URLS.get(plaid_env, _BASE_URLS["sandbox"])
    payload = {
        "client_id": client_id,
        "secret": secret,
        "identity_verification_id": session_id,
    }

    with httpx.Client(timeout=15.0) as client:
        response = client.post(
            f"{base_url}/identity_verification/get",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    return _parse_session(data)


def _parse_session(data: dict) -> IDVSession:
    session_id = data.get("id", "")
    raw_status = data.get("status", "active")
    try:
        status = IDVStatus(raw_status)
    except ValueError:
        status = IDVStatus.active

    shareable_url = data.get("shareable_url")

    # Step outcomes
    steps = data.get("steps", {})
    documentary = steps.get("documentary", {})
    selfie = steps.get("selfie_check", {})
    doc_status = documentary.get("status", "") if isinstance(documentary, dict) else ""
    selfie_status = selfie.get("status", "") if isinstance(selfie, dict) else ""
    documentary_verified = doc_status == "success"
    selfie_verified = selfie_status == "success"

    # Failure reasons
    failure_reasons: list[str] = []
    for step_name, step_data in steps.items():
        if not isinstance(step_data, dict):
            continue
        if step_data.get("status") == "failed":
            reason = step_data.get("reason") or step_name
            failure_reasons.append(f"{step_name}: {reason}")

    # Extracted PII (only present on success)
    user = data.get("user", {}) or {}
    name = user.get("name") or {}
    given_name = name.get("given_name") if isinstance(name, dict) else None
    family_name = name.get("family_name") if isinstance(name, dict) else None
    date_of_birth = user.get("date_of_birth")
    address = user.get("address") or {}
    country = address.get("country") if isinstance(address, dict) else None

    return IDVSession(
        session_id=session_id,
        status=status,
        shareable_url=shareable_url,
        documentary_verified=documentary_verified,
        selfie_verified=selfie_verified,
        given_name=given_name,
        family_name=family_name,
        date_of_birth=date_of_birth,
        country=country,
        failure_reasons=failure_reasons,
    )
