"""Read-only shared treasury wallet views for XRPL Testnet and Devnet."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from .. import xrpl_client
from ..config import get_settings
from ..schemas import WalletBalance, WalletNetworkSnapshot, WalletOverview, WalletTransaction

RIPPLE_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)


def connected_address() -> str:
    """Return only the wallet's public address; never expose or log its seed."""
    settings = get_settings()
    if settings.treasury_wallet_address.strip():
        return settings.treasury_wallet_address.strip()
    if not settings.treasury_wallet_seed.strip():
        raise ValueError("No shared treasury wallet is configured")
    from xrpl.wallet import Wallet

    return Wallet.from_seed(settings.treasury_wallet_seed).classic_address


def _xrp_from_drops(value: Any) -> str:
    return format(Decimal(str(value or "0")) / Decimal("1000000"), "f")


def _currency_label(value: str) -> str:
    if len(value) == 40:
        try:
            decoded = bytes.fromhex(value).rstrip(b"\0").decode("utf-8")
            return decoded or value
        except (ValueError, UnicodeDecodeError):
            pass
    return value


def _amount(value: Any) -> WalletBalance | None:
    if isinstance(value, str):
        return WalletBalance(currency="XRP", value=_xrp_from_drops(value))
    if isinstance(value, dict) and value.get("currency") and value.get("value") is not None:
        return WalletBalance(
            currency=_currency_label(str(value["currency"])),
            value=str(value["value"]),
            issuer=value.get("issuer"),
        )
    return None


def _transaction(item: dict[str, Any], address: str, network: str) -> WalletTransaction:
    tx = item.get("tx_json") or item.get("tx") or {}
    tx_hash = str(item.get("hash") or tx.get("hash") or "")
    sender = tx.get("Account")
    destination = tx.get("Destination")
    if sender == address and destination == address:
        direction, counterparty = "self", address
    elif sender == address:
        direction, counterparty = "outgoing", destination
    elif destination == address:
        direction, counterparty = "incoming", sender
    else:
        direction, counterparty = "related", sender or destination
    date = tx.get("date")
    timestamp = RIPPLE_EPOCH + timedelta(seconds=int(date)) if date is not None else None
    meta = item.get("meta") or {}
    result = meta.get("TransactionResult") if isinstance(meta, dict) else None
    endpoint = "devnet" if network == "devnet" else "testnet"
    explorer = (
        f"{xrpl_client.DEVNET_EXPLORER if endpoint == 'devnet' else xrpl_client.TESTNET_EXPLORER}"
        f"/transactions/{tx_hash}"
    )
    return WalletTransaction(
        hash=tx_hash,
        transaction_type=str(tx.get("TransactionType") or "Unknown"),
        direction=direction,
        counterparty=counterparty,
        amount=_amount(tx.get("Amount")),
        fee_xrp=_xrp_from_drops(tx["Fee"]) if tx.get("Fee") is not None else None,
        result=result,
        ledger_index=item.get("ledger_index") or tx.get("ledger_index"),
        timestamp=timestamp,
        explorer_url=explorer,
    )


async def fetch_network(address: str, network: str, endpoint: str) -> WalletNetworkSnapshot:
    from xrpl.models.requests import AccountInfo, AccountLines, AccountTx

    explorer_base = xrpl_client.DEVNET_EXPLORER if network == "devnet" else xrpl_client.TESTNET_EXPLORER
    base = dict(
        network=network,
        account_explorer_url=f"{explorer_base}/accounts/{address}",
    )
    try:
        async with xrpl_client.async_client(endpoint) as client:
            info_response = await client.request(AccountInfo(account=address, ledger_index="validated"))
            info = info_response.result
            if info.get("error") in {"actNotFound", "accountNotFound"}:
                return WalletNetworkSnapshot(
                    **base, active=False, xrp_balance="0", token_balances=[], transactions=[],
                    error="Account is not funded on this network.",
                )
            if info.get("error"):
                raise RuntimeError(str(info.get("error_message") or info["error"]))
            lines_response = await client.request(AccountLines(account=address, ledger_index="validated", limit=400))
            tx_response = await client.request(
                AccountTx(account=address, ledger_index_min=-1, ledger_index_max=-1, limit=25)
            )
        account_data = info.get("account_data", {})
        lines = lines_response.result.get("lines", [])
        transactions = tx_response.result.get("transactions", [])
        return WalletNetworkSnapshot(
            **base,
            active=True,
            xrp_balance=_xrp_from_drops(account_data.get("Balance", "0")),
            token_balances=[
                WalletBalance(
                    currency=_currency_label(str(line.get("currency", ""))),
                    value=str(line.get("balance", "0")),
                    issuer=line.get("account"),
                )
                for line in lines
            ],
            owner_count=account_data.get("OwnerCount"),
            sequence=account_data.get("Sequence"),
            ledger_index=info.get("ledger_index"),
            transactions=[_transaction(item, address, network) for item in transactions],
        )
    except Exception as exc:
        return WalletNetworkSnapshot(
            **base, active=False, xrp_balance="0", token_balances=[], transactions=[],
            error=f"Ledger unavailable: {exc}",
        )


async def get_overview() -> WalletOverview:
    settings = get_settings()
    address = connected_address()
    networks = await asyncio.gather(
        fetch_network(address, "testnet", settings.wallet_testnet_endpoint),
        fetch_network(address, "devnet", settings.wallet_devnet_endpoint),
    )
    return WalletOverview(address=address, fetched_at=datetime.now(timezone.utc), networks=list(networks))
