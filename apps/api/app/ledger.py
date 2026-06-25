"""XRPL ledger adapter — submits real transactions, selected once per call via settings.

Centralises the XRPL seam that was inlined across five tool modules:
- wallet(seed) eliminates scattered Wallet.from_seed calls
- treasury_wallet property covers the common treasury-seed case
- amount(currency, value) eliminates _token_amount duplicated in execution + routing
- submit(tx, wallet, endpoint) wraps submit_and_wait + client management
- explorer_url(tx_hash, endpoint) returns the real explorer URL

Usage: each tool does `settings = get_settings(); ledger = Ledger(settings)` so
existing monkeypatches on `module.get_settings` keep working.
"""

from __future__ import annotations

from typing import Any

from . import xrpl_client


class Ledger:
    """XRPL operations adapter — wraps real xrpl-py."""

    def __init__(self, settings: Any) -> None:
        self._s = settings

    def wallet(self, seed: str) -> Any:
        """Return a Wallet for seed."""
        from xrpl.wallet import Wallet

        return Wallet.from_seed(seed)

    @property
    def treasury_wallet(self) -> Any:
        return self.wallet(self._s.treasury_wallet_seed)

    def amount(self, currency: str, value: float) -> Any:
        """Build an XRPL amount: drops string for XRP, IssuedCurrencyAmount for tokens."""
        if currency.upper() == "XRP":
            from xrpl.utils import xrp_to_drops

            return xrp_to_drops(value)
        from xrpl.models.amounts import IssuedCurrencyAmount

        return IssuedCurrencyAmount(
            currency=xrpl_client.currency_code(currency),
            issuer=self._s.token_issuer_address,
            value=str(value),
        )

    async def submit(self, tx: Any, wallet: Any, endpoint: str | None = None) -> dict:
        """Sign and submit a transaction; return the result dict."""
        from xrpl.asyncio.transaction import submit_and_wait

        async with xrpl_client.async_client(endpoint) as client:
            response = await submit_and_wait(tx, client, wallet)
        return response.result

    def explorer_url(self, tx_hash: str, endpoint: str | None = None) -> str | None:
        if endpoint:
            return xrpl_client.explorer_tx_url_for(tx_hash, endpoint)
        return xrpl_client.explorer_tx_url(tx_hash)
