"""XRPL ledger adapter — real or mock, selected once per call via settings.

Centralises the mock/real seam that was inlined across five tool modules:
- wallet(seed) eliminates scattered Wallet.from_seed calls
- treasury_wallet property covers the common treasury-seed case
- amount(currency, value) eliminates _token_amount duplicated in execution + routing
- submit(tx, wallet, endpoint) wraps submit_and_wait + client management
- mock_hash(kind, key) eliminates the identical helper copied into four modules
- explorer_url(tx_hash, endpoint) returns None in mock, real URL in real mode

Usage: each tool does `settings = get_settings(); ledger = Ledger(settings)` so
existing monkeypatches on `module.get_settings` keep working in tests.
"""

from __future__ import annotations

import hashlib
from typing import Any

from . import xrpl_client


class _MockWallet:
    """Minimal stand-in for xrpl.wallet.Wallet used in mock mode."""

    def __init__(self, seed: str) -> None:
        h = hashlib.sha256(seed.encode()).hexdigest()
        self.address = f"r{h[:32].upper()}"
        self.seed = seed


class Ledger:
    """XRPL operations adapter — wraps real xrpl-py or returns mock results."""

    def __init__(self, settings: Any) -> None:
        self._s = settings

    @property
    def is_mock(self) -> bool:
        return self._s.use_mock_xrpl

    def wallet(self, seed: str) -> Any:
        """Return a Wallet for seed (real) or a mock wallet-like object."""
        if self.is_mock:
            return _MockWallet(seed)
        from xrpl.wallet import Wallet
        return Wallet.from_seed(seed)

    @property
    def treasury_wallet(self) -> Any:
        return self.wallet(self._s.treasury_wallet_seed)

    def amount(self, currency: str, value: float) -> Any:
        """Build an XRPL amount: drops string for XRP, IssuedCurrencyAmount for tokens."""
        if currency.upper() == "XRP":
            if self.is_mock:
                return str(int(value * 1_000_000))
            from xrpl.utils import xrp_to_drops
            return xrp_to_drops(value)
        if self.is_mock:
            return {"currency": currency, "issuer": self._s.token_issuer_address, "value": str(value)}
        from xrpl.models.amounts import IssuedCurrencyAmount
        return IssuedCurrencyAmount(
            currency=xrpl_client.currency_code(currency), issuer=self._s.token_issuer_address, value=str(value)
        )

    async def submit(self, tx: Any, wallet: Any, endpoint: str | None = None) -> dict:
        """Sign and submit a transaction; return the result dict."""
        from xrpl.asyncio.transaction import submit_and_wait
        async with xrpl_client.async_client(endpoint) as client:
            response = await submit_and_wait(tx, client, wallet)
        return response.result

    def explorer_url(self, tx_hash: str, endpoint: str | None = None) -> str | None:
        if self.is_mock:
            return None
        if endpoint:
            return xrpl_client.explorer_tx_url_for(tx_hash, endpoint)
        return xrpl_client.explorer_tx_url(tx_hash)

    @staticmethod
    def mock_hash(kind: str, key: str) -> str:
        return hashlib.sha256(f"{kind}:{key}".encode()).hexdigest().upper()
