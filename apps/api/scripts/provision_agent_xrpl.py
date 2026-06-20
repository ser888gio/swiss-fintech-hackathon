#!/usr/bin/env python3
"""Provision the agent's XRPL wallets and services on Testnet AND Devnet.

Idempotent, multi-network setup for the Autonomous Treasury Agent. It funds the
*existing* agent wallets — loaded from the seeds in .env, never printed — on both
Testnet and Devnet from the public faucets, optionally establishes the Testnet
RLUSD trust line (the x402 settlement asset), and prints a status matrix with
explorer links proving each account is live.

Why this exists alongside `smoke_xrpl.py`:
  `smoke_xrpl.py fund` GENERATES A NEW wallet and rewrites TREASURY_WALLET_SEED.
  This script never does that. An XRPL address is derived from the keypair, not
  the network, so the same treasury/subject address can be funded independently
  on both Testnet and Devnet. This script funds the wallets you already have so
  one identity works across both ledgers — exactly what the agentic-transaction
  and x402 flows need.

Every transaction it signs carries:
  * SourceTag 20260530  — the XRPL AI Starter Kit attribution tag, so agent
    activity is filterable on-chain (see xrpl.org/docs/agents/track-agent-behavior).
  * a Memo               — a short audit string for the on-ledger trail.

Run from apps/api (venv active, requirements installed):

    python scripts/provision_agent_xrpl.py status            # matrix only, read-only
    python scripts/provision_agent_xrpl.py provision         # fund both nets (idempotent)
    python scripts/provision_agent_xrpl.py provision --rlusd # + Testnet RLUSD trust line
    python scripts/provision_agent_xrpl.py verify            # live tagged payment per net

Seeds are read from the same settings the API uses (env / root .env) and are
never written to logs, stdout, or any file. Only public addresses are displayed.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass

# Make `app` importable when run as a plain script from apps/api.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings  # noqa: E402
from app.xrpl_client import currency_code  # noqa: E402

# XRPL AI Starter Kit attribution tag — every agent-signed tx carries it.
AGENT_SOURCE_TAG = 20260530

# Minimum XRP a wallet should hold on a network before we consider it provisioned.
# The base reserve is 1 XRP + 0.2 XRP/owned object; this leaves comfortable
# headroom for escrows, trust lines, and fees during a demo.
MIN_FUNDED_XRP = 20.0

# Testnet-only RLUSD issuer (confirmed in the xrpl-payments skill). RLUSD does
# not exist on Devnet, so the trust line is only ever set on Testnet.
RLUSD_TESTNET_ISSUER = "rQhWct2fv4Vc4KRjRgMrxa8xPN9Zx9iLKV"


@dataclass(frozen=True)
class Network:
    name: str
    endpoint: str
    explorer: str
    faucet: bool  # whether a public faucet exists for this network


NETWORKS = [
    Network("testnet", "wss://s.altnet.rippletest.net:51233", "https://testnet.xrpl.org", True),
    Network("devnet", "wss://s.devnet.rippletest.net:51233", "https://devnet.xrpl.org", True),
]


def _client(endpoint: str):
    from xrpl.asyncio.clients import AsyncWebsocketClient

    return AsyncWebsocketClient(endpoint)


def _agent_wallets(settings):
    """Map of label -> Wallet for every distinct agent seed in the environment.

    Distinct seeds only: the credential issuer reuses the treasury seed and the
    insurance vault reuses the subject address, so funding the two base wallets
    covers every on-ledger identity the agent uses.
    """
    from xrpl.wallet import Wallet

    seeds = {
        "treasury": settings.treasury_wallet_seed,
        "subject": settings.credential_subject_seed,
    }
    wallets = {}
    seen: set[str] = set()
    for label, seed in seeds.items():
        if not seed.strip():
            continue
        wallet = Wallet.from_seed(seed)
        if wallet.classic_address in seen:
            continue
        seen.add(wallet.classic_address)
        wallets[label] = wallet
    if not wallets:
        sys.exit("No agent seeds configured (set TREASURY_WALLET_SEED in .env).")
    return wallets


def _memo(text: str):
    from xrpl.models.transactions import Memo

    return Memo(memo_type=b"agent/v1".hex().upper(), memo_data=text.encode().hex().upper())


async def _balance_xrp(client, address: str):
    """Return float XRP balance, or None if the account is not funded/active."""
    from xrpl.models.requests import AccountInfo
    from xrpl.utils import drops_to_xrp

    response = await client.request(AccountInfo(account=address, ledger_index="validated"))
    if response.result.get("error"):
        return None
    return float(drops_to_xrp(response.result["account_data"]["Balance"]))


async def _has_trust_line(client, address: str, currency_hex: str, issuer: str) -> bool:
    from xrpl.models.requests import AccountLines

    response = await client.request(AccountLines(account=address, peer=issuer, ledger_index="validated"))
    if response.result.get("error"):
        return False
    return any(
        str(line.get("currency", "")).upper() == currency_hex.upper()
        for line in response.result.get("lines", [])
    )


# ── status ──────────────────────────────────────────────────────────────────

async def cmd_status(settings, _args) -> None:
    wallets = _agent_wallets(settings)
    print("Agent wallets (public addresses):")
    for label, wallet in wallets.items():
        print(f"  {label:9s}: {wallet.classic_address}")
    print()
    header = f"{'wallet':9s} {'network':8s} {'balance':>16s}  explorer"
    print(header)
    print("-" * len(header))
    for net in NETWORKS:
        async with _client(net.endpoint) as client:
            for label, wallet in wallets.items():
                balance = await _balance_xrp(client, wallet.classic_address)
                shown = f"{balance:.6f} XRP" if balance is not None else "NOT FUNDED"
                url = f"{net.explorer}/accounts/{wallet.classic_address}"
                print(f"{label:9s} {net.name:8s} {shown:>16s}  {url}")


# ── provision ───────────────────────────────────────────────────────────────

async def _fund_existing(client, wallet, net: Network, *, attempts: int = 5) -> float:
    """Fund an existing wallet from the network faucet. Returns the new balance.

    The public faucets are IP-rate-limited and return HTTP 429 under load, so a
    transient 429 is retried with linear backoff rather than aborting the run.
    """
    from xrpl.asyncio.wallet import generate_faucet_wallet

    for attempt in range(1, attempts + 1):
        try:
            # Passing the existing wallet funds THAT account, not a new mint.
            await generate_faucet_wallet(client, wallet=wallet, debug=False)
            # Faucet funding is applied in a validated ledger before this returns.
            return await _balance_xrp(client, wallet.classic_address) or 0.0
        except Exception as exc:  # noqa: BLE001 - inspect for the rate-limit case only
            if "429" in str(exc) and attempt < attempts:
                wait = 15 * attempt
                print(f"    faucet rate-limited (429); retry {attempt}/{attempts - 1} in {wait}s ...")
                await asyncio.sleep(wait)
                continue
            raise


async def _ensure_rlusd_trust_line(client, wallet, net: Network) -> None:
    from xrpl.asyncio.transaction import submit_and_wait
    from xrpl.models.amounts import IssuedCurrencyAmount
    from xrpl.models.transactions import TrustSet

    currency_hex = currency_code("RLUSD")
    if await _has_trust_line(client, wallet.classic_address, currency_hex, RLUSD_TESTNET_ISSUER):
        print(f"    RLUSD trust line already present on {net.name}.")
        return
    print(f"    Setting RLUSD trust line {wallet.classic_address} -> {RLUSD_TESTNET_ISSUER} ...")
    tx = TrustSet(
        account=wallet.classic_address,
        source_tag=AGENT_SOURCE_TAG,
        limit_amount=IssuedCurrencyAmount(currency=currency_hex, issuer=RLUSD_TESTNET_ISSUER, value="1000000"),
        memos=[_memo("rlusd-trustline")],
    )
    response = await submit_and_wait(tx, client, wallet)
    engine = (response.result.get("meta") or {}).get("TransactionResult")
    tx_hash = response.result.get("hash")
    print(f"    -> {engine}  {net.explorer}/transactions/{tx_hash}")
    if engine != "tesSUCCESS":
        sys.exit(f"TrustSet failed: {engine}")


async def cmd_provision(settings, args) -> None:
    wallets = _agent_wallets(settings)
    print(f"Provisioning {len(wallets)} wallet(s) across {len(NETWORKS)} network(s). "
          f"Floor = {MIN_FUNDED_XRP} XRP.\n")
    for net in NETWORKS:
        print(f"== {net.name} ({net.endpoint}) ==")
        async with _client(net.endpoint) as client:
            for label, wallet in wallets.items():
                balance = await _balance_xrp(client, wallet.classic_address)
                if balance is None:
                    print(f"  {label}: not funded — requesting from faucet ...")
                    balance = await _fund_existing(client, wallet, net)
                    print(f"  {label}: funded -> {balance:.6f} XRP")
                elif balance < MIN_FUNDED_XRP:
                    print(f"  {label}: {balance:.6f} XRP < floor — topping up ...")
                    balance = await _fund_existing(client, wallet, net)
                    print(f"  {label}: topped up -> {balance:.6f} XRP")
                else:
                    print(f"  {label}: already funded ({balance:.6f} XRP) — skipping")
            # RLUSD trust line is a Testnet-only service (issuer is Testnet-only).
            if args.rlusd and net.name == "testnet":
                await _ensure_rlusd_trust_line(client, wallets["treasury"], net)
        print()
    print("Provisioning complete. Run `status` to see the final matrix.")


# ── verify ──────────────────────────────────────────────────────────────────

async def cmd_verify(settings, args) -> None:
    """Submit a small SourceTag-tagged XRP payment on each network as live proof."""
    from xrpl.asyncio.transaction import submit_and_wait
    from xrpl.models.transactions import Payment
    from xrpl.utils import xrp_to_drops

    wallets = _agent_wallets(settings)
    sender = wallets["treasury"]
    # Prefer paying the subject wallet; fall back to a self-payment if it's the only one.
    recipient = wallets.get("subject", sender).classic_address
    amount_xrp = args.amount

    for net in NETWORKS:
        print(f"== {net.name}: {amount_xrp} XRP  {sender.classic_address} -> {recipient} ==")
        async with _client(net.endpoint) as client:
            balance = await _balance_xrp(client, sender.classic_address)
            if balance is None:
                print(f"  SKIP: treasury not funded on {net.name}. Run `provision` first.\n")
                continue
            tx = Payment(
                account=sender.classic_address,
                destination=recipient,
                amount=xrp_to_drops(float(amount_xrp)),
                source_tag=AGENT_SOURCE_TAG,
                memos=[_memo("agent-verify")],
            )
            response = await submit_and_wait(tx, client, sender)
        result = response.result
        engine = (result.get("meta") or {}).get("TransactionResult")
        tx_hash = result.get("hash")
        print(f"  Result : {engine}")
        print(f"  Hash   : {tx_hash}")
        print(f"  Tx     : {net.explorer}/transactions/{tx_hash}")
        print(f"  Tagged : SourceTag={AGENT_SOURCE_TAG}\n")
        if engine != "tesSUCCESS":
            sys.exit(f"Verification payment failed on {net.name}: {engine}")
    print("Live transactions confirmed on every funded network.")


# ── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Provision agent XRPL wallets/services on Testnet + Devnet.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="read-only funding/trust-line matrix")
    prov = sub.add_parser("provision", help="fund existing wallets on both networks (idempotent)")
    prov.add_argument("--rlusd", action="store_true", help="also set the Testnet RLUSD trust line")
    ver = sub.add_parser("verify", help="submit a live tagged XRP payment on each network")
    ver.add_argument("--amount", default="1", help="amount in XRP (default: 1)")
    args = parser.parse_args()

    settings = get_settings()
    handlers = {"status": cmd_status, "provision": cmd_provision, "verify": cmd_verify}
    try:
        asyncio.run(handlers[args.command](settings, args))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - friendly message, never dump a seed-bearing traceback
        sys.exit(f"XRPL error: {exc}\n(Check endpoint reachability and that seeds are set in .env.)")


if __name__ == "__main__":
    main()
