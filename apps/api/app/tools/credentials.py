"""Treasury-facing KYC credential tool facade.

The XLS-70 implementation lives in :mod:`app.credentials.kyc.tool`, while the
orchestrator contract exposes it as ``app.tools.credentials``. Re-export the
public operations here so workflows use the documented tool boundary.
"""

from ..credentials.kyc.tool import (
    MOCK_UNVERIFIED_SUBJECTS,
    accept_credential,
    issue_credential,
    reset_mock_state,
    verify_kyc,
)

__all__ = [
    "MOCK_UNVERIFIED_SUBJECTS",
    "accept_credential",
    "issue_credential",
    "reset_mock_state",
    "verify_kyc",
]
