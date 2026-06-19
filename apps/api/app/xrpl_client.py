"""Thin XRPL helpers shared by the execution, routing and credentials tools.

Kept small on purpose: the tools own transaction building, this module owns
connection details, explorer URLs, pathfinding, and credential lookups.

`xrpl-py` is imported lazily inside each function so mock mode (and the test
suite) never need the dependency loaded. Only real-mode code paths pull it in.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .config import get_settings

TESTNET_EXPLORER = "https://testnet.xrpl.org"
DEVNET_EXPLORER = "https://devnet.xrpl.org"
MAINNET_EXPLORER = "https://livenet.xrpl.org"
# Cross-check explorer. xrpscan has no Testnet view, so bithomp's Testnet
# instance is used as the second source for the verification matrix.
BITHOMP_TESTNET_EXPLORER = "https://test.bithomp.com"

# lsfAccepted on a Credential ledger entry: the subject has accepted the
# credential, so it is usable. An unaccepted credential must be ignored.
LSF_ACCEPTED = 0x00010000


def _explorer_base(endpoint: str | None) -> str:
    """Map an XRPL endpoint to its block explorer (devnet/testnet/mainnet).

    Checked devnet-first because both devnet and testnet hosts contain
    'rippletest.net'. An unrecognized (e.g. xrplcluster.com) endpoint is treated
    as mainnet — so explorer links stay correct on the path to production.
    """
    ep = endpoint or ""
    if "devnet" in ep:
        return DEVNET_EXPLORER
    if any(token in ep for token in ("altnet", "testnet", "rippletest")):
        return TESTNET_EXPLORER
    return MAINNET_EXPLORER


def explorer_tx_url(tx_hash: str) -> str:
    """Network-aware tx explorer link for the currently configured endpoint."""
    return f"{_explorer_base(get_settings().xrpl_endpoint)}/transactions/{tx_hash}"


def explorer_account_url(address: str) -> str:
    return f"{_explorer_base(get_settings().xrpl_endpoint)}/accounts/{address}"


def bithomp_tx_url(tx_hash: str) -> str:
    """Second explorer link for a transaction (cross-check source)."""
    return f"{BITHOMP_TESTNET_EXPLORER}/explorer/{tx_hash}"


def bithomp_account_url(address: str) -> str:
    return f"{BITHOMP_TESTNET_EXPLORER}/explorer/{address}"


def async_client(endpoint: str | None = None):
    """An XRPL async client. Uses configured endpoint when none supplied."""
    from xrpl.asyncio.clients import AsyncWebsocketClient

    return AsyncWebsocketClient(endpoint or get_settings().xrpl_endpoint)


def explorer_tx_url_for(tx_hash: str, endpoint: str) -> str:
    """Return the right block-explorer link for an explicit endpoint."""
    return f"{_explorer_base(endpoint)}/transactions/{tx_hash}"


def network_label(endpoint: str, *, use_mock: bool) -> str:
    """Network name for an endpoint: 'mock' | 'devnet' | 'testnet'."""
    if use_mock:
        return "mock"
    return "devnet" if "devnet" in endpoint else "testnet"


def mock_tx_hash(kind: str, key: str) -> str:
    """Deterministic fake tx hash for mock mode (no network access)."""
    return hashlib.sha256(f"{kind}:{key}".encode()).hexdigest().upper()


def currency_code(currency: str) -> str:
    """Normalise a currency code to XRPL wire form.

    Standard ISO-style 3-char codes (USD, EUR) pass through unchanged. Longer
    codes such as RLUSD must be sent as a 40-char hex string — xrpl-py's binary
    codec rejects anything else — so "RLUSD" becomes 524C555344 + zero padding.
    """
    from xrpl.utils import str_to_hex

    if len(currency) <= 3:
        return currency
    return str_to_hex(currency).upper().ljust(40, "0")


def token_amount(currency: str, value, settings):
    """Build an XRPL amount: drops for XRP, IssuedCurrencyAmount for a token."""
    if currency.upper() == "XRP":
        from xrpl.utils import xrp_to_drops

        return xrp_to_drops(value)
    from xrpl.models.amounts import IssuedCurrencyAmount

    return IssuedCurrencyAmount(
        currency=currency_code(currency), issuer=settings.token_issuer_address, value=str(value)
    )


def to_wire_amount(amount, currency: str, settings):
    """Convert a Decimal (or int/float) amount to the XRPL wire format.

    This is the ONLY place in new code where money crosses the ledger boundary.
    All new modules must call this instead of constructing IssuedCurrencyAmount
    directly, so the Decimal invariant is enforced at one location.

    - XRP  → drops (str, via xrp_to_drops)
    - token → IssuedCurrencyAmount with value=str(amount) (6dp canonical form)

    Accepts Decimal, int, or float; callers in new code must pass Decimal.
    """
    from decimal import Decimal, ROUND_DOWN

    d = Decimal(str(amount)).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
    return token_amount(currency, d, settings)


def credential_type_hex(credential_type: str) -> str:
    """XRPL stores CredentialType as uppercase hex of the UTF-8 bytes."""
    from xrpl.utils import str_to_hex

    return str_to_hex(credential_type).upper()


async def find_payment_paths(
    source_account: str, destination_account: str, destination_amount: Any
) -> list[dict]:
    """Run ripple_path_find and return the ranked alternatives.

    Each alternative carries `paths_computed` (the Paths set) and `source_amount`
    (what the sender would spend). The caller picks the cheapest and caps SendMax.
    """
    from xrpl.models.requests import RipplePathFind

    request = RipplePathFind(
        source_account=source_account,
        destination_account=destination_account,
        destination_amount=destination_amount,
    )
    async with async_client() as client:
        response = await client.request(request)
    return response.result.get("alternatives", [])


async def lookup_accepted_credential(
    subject: str, issuer: str, credential_type_hex_value: str
) -> dict | None:
    """Return the subject's accepted credential matching issuer + type, or None.

    Only credentials with the lsfAccepted flag set are returned; an issued but
    unaccepted credential is not yet valid (the subject must CredentialAccept).
    """
    from xrpl.models.requests import AccountObjects

    async with async_client() as client:
        response = await client.request(
            AccountObjects(account=subject, type="credential")
        )
    for obj in response.result.get("account_objects", []):
        if obj.get("Issuer") != issuer:
            continue
        if obj.get("CredentialType") != credential_type_hex_value:
            continue
        if not int(obj.get("Flags", 0)) & LSF_ACCEPTED:
            continue
        return obj
    return None
