#!/usr/bin/env python3
"""Set up a self-issued IOU on Devnet for use as the treasury settlement token.

This script:
  1. Funds two fresh Devnet wallets (treasury + issuer) from the faucet.
  2. Creates a trust line from treasury ->issuer for the chosen currency.
  3. Issues tokens from issuer ->treasury.
  4. Prints the .env snippet to copy.

Run from apps/api (after activating the venv):

    python scripts/setup_devnet_iou.py

Options:
    --currency RUSD     3-char currency code (default: RUSD)
    --amount 100000     how many tokens to issue (default: 100000)
    --endpoint wss://s.devnet.rippletest.net:51233

IMPORTANT: save the seeds printed — they are not stored anywhere.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

DEVNET_FAUCET = "https://faucet.devnet.rippletest.net/accounts"
DEVNET_WS = "wss://s.devnet.rippletest.net:51233"
DEVNET_EXPLORER = "https://devnet.xrpl.org"


# ── Faucet ────────────────────────────────────────────────────────────────────

async def fund_from_faucet(faucet_url: str, label: str) -> tuple[str, str]:
    """POST to the Devnet faucet, return (address, seed)."""
    import httpx

    print(f"  Funding {label} from faucet…", end=" ", flush=True)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(faucet_url)
        r.raise_for_status()
        data = r.json()

    # Faucet shape: {"account": {"address": "r…", "classicAddress": "r…"}, "seed": "s…"}
    acct = data.get("account") or data
    address = acct.get("address") or acct.get("classicAddress")
    # seed can be top-level or inside account depending on faucet version
    seed = data.get("seed") or acct.get("secret") or acct.get("seed")
    if not address or not seed:
        sys.exit(f"Unexpected faucet response: {data}")
    print(f"done ->{address}")
    return address, seed


# ── XRPL helpers ─────────────────────────────────────────────────────────────

def _ws_client(endpoint: str):
    from xrpl.asyncio.clients import AsyncWebsocketClient
    return AsyncWebsocketClient(endpoint)


async def _submit(client, tx, wallet) -> dict:
    from xrpl.asyncio.transaction import autofill_and_sign, submit
    signed = await autofill_and_sign(tx, client, wallet)
    result = await submit(signed, client)
    meta = result.result.get("meta") or {}
    engine = meta.get("TransactionResult") or result.result.get("engine_result", "")
    if not engine.startswith("tes"):
        raise RuntimeError(f"Transaction failed: {engine} — {result.result}")
    return result.result


async def wait_for_ledger(client) -> None:
    """Wait one ledger close (~4 s) so the previous tx is confirmed."""
    from xrpl.models.requests import Ledger as LedgerReq
    r1 = await client.request(LedgerReq(ledger_index="validated"))
    start = r1.result["ledger_index"]
    while True:
        await asyncio.sleep(2)
        r2 = await client.request(LedgerReq(ledger_index="validated"))
        if r2.result["ledger_index"] > start:
            return


# ── Main setup flow ───────────────────────────────────────────────────────────

async def setup(currency: str, amount: str, endpoint: str) -> None:
    from xrpl.models.amounts import IssuedCurrencyAmount
    from xrpl.models.transactions import Payment, TrustSet
    from xrpl.wallet import Wallet

    print(f"\n{'='*60}")
    print(f"  Devnet IOU setup  |  currency={currency}  amount={amount}")
    print(f"  endpoint: {endpoint}")
    print(f"{'='*60}\n")

    # 1. Fund wallets
    treasury_addr, treasury_seed = await fund_from_faucet(DEVNET_FAUCET, "treasury")
    await asyncio.sleep(2)  # slight stagger to avoid faucet rate-limit
    issuer_addr, issuer_seed = await fund_from_faucet(DEVNET_FAUCET, "issuer")

    treasury_wallet = Wallet.from_seed(treasury_seed)
    issuer_wallet = Wallet.from_seed(issuer_seed)

    print(f"\n  Waiting for faucet ledger close…")
    await asyncio.sleep(6)

    async with _ws_client(endpoint) as client:
        # 2. Trust line: treasury trusts issuer for `currency` up to `amount`
        print(f"  Creating trust line {treasury_addr} ->{issuer_addr} for {currency}…", end=" ", flush=True)
        trust_limit = IssuedCurrencyAmount(
            currency=currency,
            issuer=issuer_addr,
            value=str(int(amount) * 10),  # trust limit = 10× issue amount
        )
        trust_tx = TrustSet(
            account=treasury_addr,
            limit_amount=trust_limit,
        )
        await _submit(client, trust_tx, treasury_wallet)
        print("done")

        await wait_for_ledger(client)

        # 3. Issue tokens: issuer ->treasury
        print(f"  Issuing {amount} {currency} to treasury…", end=" ", flush=True)
        issue_amount = IssuedCurrencyAmount(
            currency=currency,
            issuer=issuer_addr,
            value=amount,
        )
        payment_tx = Payment(
            account=issuer_addr,
            destination=treasury_addr,
            amount=issue_amount,
        )
        result = await _submit(client, payment_tx, issuer_wallet)
        tx_hash = result.get("hash") or result.get("tx_json", {}).get("hash", "")
        print(f"done ->{DEVNET_EXPLORER}/transactions/{tx_hash}")

        await wait_for_ledger(client)

        # 4. Verify balance
        from xrpl.models.requests import AccountLines
        r = await client.request(AccountLines(account=treasury_addr, ledger_index="validated"))
        lines = r.result.get("lines", [])
        found = next((l for l in lines if l["currency"] == currency), None)
        balance = found["balance"] if found else "NOT FOUND"
        print(f"\n  Treasury balance: {balance} {currency}")

    # 5. Print .env snippet
    print(f"""
{'='*60}
  SUCCESS — copy these into your .env:
{'='*60}

XRPL_ENDPOINT={endpoint}
TREASURY_WALLET_SEED={treasury_seed}
RELEASE_WALLET_SEED={treasury_seed}
TOKEN_CURRENCY={currency}
TOKEN_ISSUER_ADDRESS={issuer_addr}
USE_MOCK_XRPL=false
XRPL_NETWORK=xrpl:devnet
VAULT_XRPL_ENDPOINT={endpoint}

# Issuer seed (keep safe, needed to top up treasury later):
# ISSUER_SEED={issuer_seed}
# ISSUER_ADDRESS={issuer_addr}

# Treasury address (for TREASURY_WALLET_ADDRESS):
TREASURY_WALLET_ADDRESS={treasury_addr}

# Explorer links:
#   Treasury: {DEVNET_EXPLORER}/accounts/{treasury_addr}
#   Issuer:   {DEVNET_EXPLORER}/accounts/{issuer_addr}
{'='*60}
""")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Set up a self-issued IOU on Devnet")
    parser.add_argument("--currency", default="RUSD", help="3-char currency code (default: RUSD)")
    parser.add_argument("--amount", default="100000", help="Tokens to issue (default: 100000)")
    parser.add_argument("--endpoint", default=DEVNET_WS, help="Devnet WebSocket endpoint")
    args = parser.parse_args()

    if len(args.currency) > 3:
        sys.exit("Currency code must be 3 characters or fewer (e.g. RUSD ->use RSD, or RUSD needs hex encoding).")

    asyncio.run(setup(args.currency, args.amount, args.endpoint))


if __name__ == "__main__":
    main()
