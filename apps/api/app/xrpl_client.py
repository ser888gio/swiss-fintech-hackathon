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
# Cross-check explorer. xrpscan has no Testnet view, so bithomp's Testnet
# instance is used as the second source for the verification matrix.
BITHOMP_TESTNET_EXPLORER = "https://test.bithomp.com"

# lsfAccepted on a Credential ledger entry: the subject has accepted the
# credential, so it is usable. An unaccepted credential must be ignored.
LSF_ACCEPTED = 0x00010000


def explorer_tx_url(tx_hash: str) -> str:
    return f"{TESTNET_EXPLORER}/transactions/{tx_hash}"


def explorer_account_url(address: str) -> str:
    return f"{TESTNET_EXPLORER}/accounts/{address}"


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
    """Return the right block-explorer link based on the XRPL endpoint in use."""
    if "devnet" in endpoint:
        return f"{DEVNET_EXPLORER}/transactions/{tx_hash}"
    return explorer_tx_url(tx_hash)


def network_label(endpoint: str, *, use_mock: bool) -> str:
    """Network name for an endpoint: 'mock' | 'devnet' | 'testnet'."""
    if use_mock:
        return "mock"
    return "devnet" if "devnet" in endpoint else "testnet"


def mock_tx_hash(kind: str, key: str) -> str:
    """Deterministic fake tx hash for mock mode (no network access)."""
    return hashlib.sha256(f"{kind}:{key}".encode()).hexdigest().upper()


def token_amount(currency: str, value, settings):
    """Build an XRPL amount: drops for XRP, IssuedCurrencyAmount for a token."""
    if currency.upper() == "XRP":
        from xrpl.utils import xrp_to_drops

        return xrp_to_drops(value)
    from xrpl.models.amounts import IssuedCurrencyAmount

    return IssuedCurrencyAmount(
        currency=currency, issuer=settings.token_issuer_address, value=str(value)
    )


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
