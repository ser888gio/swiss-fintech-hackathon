#!/usr/bin/env python3
"""One-shot XRPL connectivity / payment smoke test.

Validates that your real-network setup works *outside* the full agent: it
connects to XRPL_ENDPOINT with TREASURY_WALLET_SEED, checks the balance, and can
send a real XRP payment. Use it before flipping the API to USE_MOCK_XRPL=false.

Run from apps/api (after `pip install -r requirements.txt`):

    python scripts/smoke_xrpl.py status            # XRP + configured token balance
    python scripts/smoke_xrpl.py fund              # create+fund a faucet wallet
    python scripts/smoke_xrpl.py pay <dest> <xrp>  # send XRP from the treasury
    python scripts/smoke_xrpl.py trustset RLUSD <issuer> [limit]

Reads XRPL_ENDPOINT and TREASURY_WALLET_SEED from the same settings the API uses
(env / .env). This script only ever touches XRP and is read-only except for the
explicit `fund`, `pay`, and `trustset` commands. See docs/real-xrpl.md.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Make `app` importable when run as a plain script from apps/api.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings  # noqa: E402
from app.xrpl_client import currency_code, explorer_account_url, explorer_tx_url  # noqa: E402


def _client(endpoint: str):
    from xrpl.asyncio.clients import AsyncWebsocketClient

    return AsyncWebsocketClient(endpoint)


def _treasury_wallet(settings):
    from xrpl.wallet import Wallet

    if not settings.treasury_wallet_seed:
        sys.exit("TREASURY_WALLET_SEED is not set - fund a wallet first (see `fund`).")
    return Wallet.from_seed(settings.treasury_wallet_seed)


def _warn_if_not_test_network(endpoint: str) -> None:
    if not any(token in endpoint for token in ("altnet", "devnet", "rippletest")):
        print(f"WARNING: {endpoint} does not look like Testnet/Devnet.", file=sys.stderr)


async def cmd_status(settings) -> None:
    from decimal import Decimal

    from xrpl.models.requests import AccountInfo, AccountLines
    from xrpl.utils import drops_to_xrp

    wallet = _treasury_wallet(settings)
    print(f"Endpoint : {settings.xrpl_endpoint}")
    print(f"Treasury : {wallet.address}")
    async with _client(settings.xrpl_endpoint) as client:
        response = await client.request(
            AccountInfo(account=wallet.address, ledger_index="validated")
        )
        lines_response = None
        if settings.token_issuer_address:
            lines_response = await client.request(
                AccountLines(
                    account=wallet.address,
                    peer=settings.token_issuer_address,
                    ledger_index="validated",
                )
            )
    if not response.is_successful():
        print(f"account_info failed: {response.result.get('error_message') or response.result}")
        print("(An unfunded account returns actNotFound - run `fund` or send it XRP.)")
        return
    balance_drops = response.result["account_data"]["Balance"]
    print(f"Balance  : {drops_to_xrp(balance_drops)} XRP")
    if lines_response is not None:
        if not lines_response.is_successful():
            print(
                "Token    : account_lines failed: "
                f"{lines_response.result.get('error_message') or lines_response.result}"
            )
        else:
            expected_currency = currency_code(settings.token_currency).upper()
            balances = [
                Decimal(str(line["balance"]))
                for line in lines_response.result.get("lines", [])
                if str(line.get("currency", "")).upper() == expected_currency
            ]
            balance = sum(balances, Decimal("0"))
            trust_line = "present" if balances else "missing"
            print(f"Token    : {balance} {settings.token_currency} (trust line {trust_line})")
    print(f"Explorer : {explorer_account_url(wallet.address)}")


async def cmd_fund(settings) -> None:
    from dotenv import set_key
    from xrpl.asyncio.wallet import generate_faucet_wallet

    _warn_if_not_test_network(settings.xrpl_endpoint)
    print(f"Requesting a funded wallet from the {settings.xrpl_endpoint} faucet...")
    async with _client(settings.xrpl_endpoint) as client:
        wallet = await generate_faucet_wallet(client, debug=False)
    root_env = Path(__file__).resolve().parents[3] / ".env"
    root_env.touch(exist_ok=True)
    set_key(str(root_env), "TREASURY_WALLET_SEED", wallet.seed, quote_mode="always")
    set_key(str(root_env), "TREASURY_WALLET_ADDRESS", wallet.address, quote_mode="never")
    print("\nFunded wallet created:")
    print(f"  Address : {wallet.address}")
    print("  Seed    : saved to the ignored root .env (not displayed)")
    print(f"  Explorer: {explorer_account_url(wallet.address)}")
    print("\nThe API will load this wallet from TREASURY_WALLET_SEED.")


async def cmd_pay(settings, destination: str, amount_xrp: str) -> None:
    from xrpl.asyncio.transaction import submit_and_wait
    from xrpl.models.transactions import Payment
    from xrpl.utils import xrp_to_drops

    _warn_if_not_test_network(settings.xrpl_endpoint)
    wallet = _treasury_wallet(settings)
    print(f"Sending {amount_xrp} XRP  {wallet.address} -> {destination}")
    tx = Payment(
        account=wallet.address,
        destination=destination,
        amount=xrp_to_drops(float(amount_xrp)),
    )
    async with _client(settings.xrpl_endpoint) as client:
        response = await submit_and_wait(tx, client, wallet)

    result = response.result
    engine_result = (result.get("meta") or {}).get("TransactionResult")
    tx_hash = result.get("hash")
    print(f"\nResult : {engine_result}")
    print(f"Hash   : {tx_hash}")
    if tx_hash:
        print(f"Explorer: {explorer_tx_url(tx_hash)}")
    if engine_result != "tesSUCCESS":
        sys.exit(1)


async def cmd_trustset(settings, currency: str, issuer: str, limit: str) -> None:
    """Create or update a trust line from the configured treasury wallet."""
    from xrpl.asyncio.transaction import submit_and_wait
    from xrpl.models.amounts import IssuedCurrencyAmount
    from xrpl.models.transactions import TrustSet

    _warn_if_not_test_network(settings.xrpl_endpoint)
    wallet = _treasury_wallet(settings)
    wire_currency = currency_code(currency)
    print(f"Setting {currency} trust line: {wallet.address} -> issuer {issuer} (limit {limit})")
    tx = TrustSet(
        account=wallet.address,
        limit_amount=IssuedCurrencyAmount(
            currency=wire_currency,
            issuer=issuer,
            value=limit,
        ),
    )
    async with _client(settings.xrpl_endpoint) as client:
        response = await submit_and_wait(tx, client, wallet)

    result = response.result
    engine_result = (result.get("meta") or {}).get("TransactionResult")
    tx_hash = result.get("hash")
    print(f"\nResult : {engine_result}")
    print(f"Hash   : {tx_hash}")
    if tx_hash:
        print(f"Explorer: {explorer_tx_url(tx_hash)}")
    if engine_result != "tesSUCCESS":
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="XRPL connectivity / payment smoke test.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="show endpoint + treasury balance")
    sub.add_parser("fund", help="create and fund a faucet wallet (Testnet/Devnet)")
    pay = sub.add_parser("pay", help="send XRP from the treasury wallet")
    pay.add_argument("destination", help="destination r-address")
    pay.add_argument("amount_xrp", help="amount in XRP, e.g. 1")
    trustset = sub.add_parser("trustset", help="create/update an issued-token trust line")
    trustset.add_argument("currency", help="currency code, e.g. RLUSD")
    trustset.add_argument("issuer", help="issuer r-address")
    trustset.add_argument("limit", nargs="?", default="1000000", help="trust limit (default: 1000000)")
    args = parser.parse_args()

    settings = get_settings()
    try:
        if args.command == "status":
            asyncio.run(cmd_status(settings))
        elif args.command == "fund":
            asyncio.run(cmd_fund(settings))
        elif args.command == "pay":
            asyncio.run(cmd_pay(settings, args.destination, args.amount_xrp))
        elif args.command == "trustset":
            asyncio.run(cmd_trustset(settings, args.currency, args.issuer, args.limit))
    except Exception as exc:  # noqa: BLE001 - surface a friendly message, not a traceback
        sys.exit(f"XRPL error: {exc}\n(Check XRPL_ENDPOINT reachability and your seed.)")


if __name__ == "__main__":
    main()
