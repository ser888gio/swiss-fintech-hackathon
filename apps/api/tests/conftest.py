"""Pytest configuration: pin a hermetic environment for the unit suite.

These tests mock XRPL — they assert on deterministic, offline behaviour and never
touch a real ledger. Most tests patch `get_settings` per module with a
`SimpleNamespace`, but the orchestrator's call path also reaches modules they
don't patch (e.g. `execution`, `receipt`). Those fall back to the real, cached
`Settings`, which reads the developer's root `.env`.

When that `.env` carries `USE_MOCK_XRPL=false` (set for live Testnet runs), the
unpatched `execution` tool would try to build a real XRPL `Payment`/`EscrowCreate`
from a placeholder address like ``"rReceiver"`` and fail AccountID validation —
turning a local config choice into spurious test failures.

Forcing mock mode (and clearing the `lru_cache`) here makes the suite independent
of any local `.env`. Real-network behaviour is exercised by `scripts/smoke_xrpl.py`
and the live API, not by pytest.
"""

from __future__ import annotations

import os

# Set before any test module imports `app.config` / calls `get_settings()`.
# Environment variables take precedence over `.env` files in pydantic-settings,
# so this overrides whatever USE_MOCK_XRPL the local .env defines.
os.environ.setdefault("USE_MOCK_XRPL", "true")
os.environ["USE_MOCK_XRPL"] = "true"

# Drop any Settings instance cached from a real .env read at import time.
from app.config import get_settings  # noqa: E402

get_settings.cache_clear()
