"""Thin XRPL helpers shared by the execution tool.

Kept small on purpose: the execution tool owns transaction building, this module
owns connection details and explorer URLs.
"""

from __future__ import annotations

TESTNET_EXPLORER = "https://testnet.xrpl.org"


def explorer_tx_url(tx_hash: str) -> str:
    return f"{TESTNET_EXPLORER}/transactions/{tx_hash}"
