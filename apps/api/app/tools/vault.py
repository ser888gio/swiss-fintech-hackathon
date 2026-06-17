"""Vault tool — XLS-65 Single Asset Vault + XLS-66 yield.

Deposits idle treasury RLUSD into a Single Asset Vault for passive yield
(lending rate from XLS-66). Withdraws when the wallet balance drops below
the recall threshold. The treasury agent calls these functions as its
only actuator — the LLM only narrates the outcome.

Network: XLS-65/66 are amendment-gated. At the time of build, they are
available on Devnet (wss://s.devnet.rippletest.net:51233) but not Testnet.
Set VAULT_XRPL_ENDPOINT to the Devnet endpoint before using real mode.

In mock mode (settings.use_mock_xrpl=True) all operations update an
in-memory vault state and return deterministic fake tx hashes so the
treasury agent can demonstrate the sweep loop offline. The mock wallet
balance starts at 50 000 RLUSD and is updated on every deposit/withdraw,
giving a coherent round-trip without any network access.

Byte format note: vault_id is the hex `LedgerIndex` of the Vault object
created by `VaultCreate`. Pass this as `vault_id` to Deposit/Withdraw.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..config import get_settings
from .. import xrpl_client
from ..ledger import Ledger

# ── In-memory vault state (mock mode) ────────────────────────────────────────
# Survives the process lifetime; each deposit/withdraw updates it so the sweep
# logic sees a realistic debit/credit cycle without network access.

_state: dict = {
    "vault_id": None,          # hex LedgerIndex of the Vault object (VaultCreate result)
    "deposited": 0.0,          # tokens currently inside the vault
    "shares": 0.0,             # vault shares held by treasury (MPToken balance)
    "wallet_balance": 50_000.0, # mock hot-wallet token balance (deducted on deposit)
    "operations": [],          # list[dict] — audit trail for /treasury/vault
}

# Approximate APY for narration (XLS-66 lending rate is dynamic; this is
# illustrative only and NEVER drives any financial decision).
_MOCK_APY_PCT = 4.5


@dataclass
class VaultCreateResult:
    vault_id: str
    tx_hash: str
    explorer_url: str | None


@dataclass
class VaultOpResult:
    vault_id: str
    operation: str          # "deposit" | "withdraw"
    amount: float           # tokens moved
    shares_delta: float     # vault shares minted (+) or burned (−)
    tx_hash: str
    explorer_url: str | None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def get_vault_state() -> dict:
    """Return a snapshot of the in-memory vault state (mock + real-mode cache)."""
    return {**_state, "operations": list(_state["operations"])}


# ── VaultCreate ───────────────────────────────────────────────────────────────

async def create_vault(asset_currency: str, asset_issuer: str) -> VaultCreateResult:
    """VaultCreate — creates a Single Asset Vault for the given issued token.

    In real mode the tx lands on the network configured in
    `settings.vault_xrpl_endpoint` (Devnet by default). The returned
    `vault_id` must be stored in `VAULT_ID` so deposit/withdraw can find it.
    """
    settings = get_settings()
    if settings.use_mock_xrpl:
        vault_id = _mock_vault_id(asset_currency, asset_issuer)
        tx_hash = xrpl_client.mock_tx_hash("vault_create", vault_id)
        _state["vault_id"] = vault_id
        _remember_operation("create", 0.0, tx_hash, None)
        return VaultCreateResult(vault_id=vault_id, tx_hash=tx_hash, explorer_url=None)

    from xrpl.models.currencies import IssuedCurrency
    from xrpl.models.transactions import VaultCreate

    ledger = Ledger(settings)
    wallet = ledger.treasury_wallet
    tx = VaultCreate(
        account=wallet.address,
        asset=IssuedCurrency(currency=asset_currency, issuer=asset_issuer),
    )
    result = await ledger.submit(tx, wallet, endpoint=settings.vault_xrpl_endpoint)
    tx_hash = result["hash"]
    # VaultCreate produces a Vault ledger object; its LedgerIndex is the vault_id.
    vault_id = _parse_vault_id(result) or _mock_vault_id(asset_currency, asset_issuer)
    explorer_url = xrpl_client.explorer_tx_url_for(tx_hash, settings.vault_xrpl_endpoint)
    _state["vault_id"] = vault_id
    _remember_operation("create", 0.0, tx_hash, explorer_url)
    return VaultCreateResult(
        vault_id=vault_id,
        tx_hash=tx_hash,
        explorer_url=explorer_url,
    )


# ── VaultDeposit ──────────────────────────────────────────────────────────────

async def deposit(vault_id: str, amount: float) -> VaultOpResult:
    """VaultDeposit — add tokens to the vault; receive vault shares (MPTokens).

    The actual shares minted depend on the vault's exchange rate; in mock
    mode 100 tokens = 1 share (illustrative ratio only).
    """
    settings = get_settings()
    if settings.use_mock_xrpl:
        actual = min(amount, _state["wallet_balance"])
        shares = actual / 100.0  # 100 tokens → 1 share (mock rate)
        tx_hash = xrpl_client.mock_tx_hash("vault_deposit", f"{vault_id}:{actual}")
        _state["deposited"] += actual
        _state["shares"] += shares
        _state["wallet_balance"] = max(0.0, _state["wallet_balance"] - actual)
        _state["vault_id"] = _state["vault_id"] or vault_id
        timestamp = _remember_operation("deposit", actual, tx_hash, None)
        return VaultOpResult(
            vault_id=vault_id,
            operation="deposit",
            amount=actual,
            shares_delta=shares,
            tx_hash=tx_hash,
            explorer_url=None,
            timestamp=timestamp,
        )

    from xrpl.models.transactions import VaultDeposit

    ledger = Ledger(settings)
    wallet = ledger.treasury_wallet
    tx = VaultDeposit(
        account=wallet.address,
        vault_id=vault_id,
        amount=xrpl_client.token_amount(settings.token_currency, amount, settings),
    )
    result = await ledger.submit(tx, wallet, endpoint=settings.vault_xrpl_endpoint)
    tx_hash = result["hash"]
    shares = _parse_shares_minted(result)
    explorer_url = xrpl_client.explorer_tx_url_for(tx_hash, settings.vault_xrpl_endpoint)
    _state["deposited"] += amount
    _state["shares"] += shares
    timestamp = _remember_operation("deposit", amount, tx_hash, explorer_url)
    return VaultOpResult(
        vault_id=vault_id,
        operation="deposit",
        amount=amount,
        shares_delta=shares,
        tx_hash=tx_hash,
        explorer_url=explorer_url,
        timestamp=timestamp,
    )


# ── VaultWithdraw ─────────────────────────────────────────────────────────────

async def withdraw(vault_id: str, amount: float) -> VaultOpResult:
    """VaultWithdraw — burn vault shares, receive tokens back into the treasury.

    Clamps to the amount currently deposited in mock mode so the state stays
    consistent. In real mode the vault enforces the share balance on-ledger.
    """
    settings = get_settings()
    if settings.use_mock_xrpl:
        actual = min(amount, _state["deposited"])
        shares = actual / 100.0
        tx_hash = xrpl_client.mock_tx_hash("vault_withdraw", f"{vault_id}:{actual}")
        _state["deposited"] = max(0.0, _state["deposited"] - actual)
        _state["shares"] = max(0.0, _state["shares"] - shares)
        _state["wallet_balance"] += actual
        timestamp = _remember_operation("withdraw", actual, tx_hash, None)
        return VaultOpResult(
            vault_id=vault_id,
            operation="withdraw",
            amount=actual,
            shares_delta=-shares,
            tx_hash=tx_hash,
            explorer_url=None,
            timestamp=timestamp,
        )

    from xrpl.models.transactions import VaultWithdraw

    ledger = Ledger(settings)
    wallet = ledger.treasury_wallet
    tx = VaultWithdraw(
        account=wallet.address,
        vault_id=vault_id,
        amount=xrpl_client.token_amount(settings.token_currency, amount, settings),
    )
    result = await ledger.submit(tx, wallet, endpoint=settings.vault_xrpl_endpoint)
    tx_hash = result["hash"]
    shares = _parse_shares_burned(result)
    explorer_url = xrpl_client.explorer_tx_url_for(tx_hash, settings.vault_xrpl_endpoint)
    _state["deposited"] = max(0.0, _state["deposited"] - amount)
    _state["shares"] = max(0.0, _state["shares"] - shares)
    _state["wallet_balance"] += amount
    timestamp = _remember_operation("withdraw", amount, tx_hash, explorer_url)
    return VaultOpResult(
        vault_id=vault_id,
        operation="withdraw",
        amount=amount,
        shares_delta=-shares,
        tx_hash=tx_hash,
        explorer_url=explorer_url,
        timestamp=timestamp,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_vault_id(currency: str, issuer: str) -> str:
    return hashlib.sha256(f"vault:{currency}:{issuer}".encode()).hexdigest().upper()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _remember_operation(
    operation: str,
    amount: float,
    tx_hash: str,
    explorer_url: str | None,
) -> datetime:
    timestamp = _now()
    _state["operations"].append({
        "id": str(uuid.uuid4()),
        "operation": operation,
        "amount": amount,
        "tx_hash": tx_hash,
        "explorer_url": explorer_url,
        "timestamp": timestamp.isoformat(),
    })
    return timestamp


def _parse_vault_id(result: dict) -> str | None:
    for node in result.get("meta", {}).get("AffectedNodes", []):
        created = node.get("CreatedNode", {})
        if created.get("LedgerEntryType") == "Vault":
            return created.get("LedgerIndex")
    return None


def _parse_shares_minted(result: dict) -> float:
    """Extract MPToken shares minted from VaultDeposit metadata."""
    for node in result.get("meta", {}).get("AffectedNodes", []):
        modified = node.get("ModifiedNode", {}) or node.get("CreatedNode", {})
        if modified.get("LedgerEntryType") == "MPToken":
            fields = modified.get("NewFields", {}) or modified.get("FinalFields", {})
            prev = (modified.get("PreviousFields") or {}).get("MPTAmount", "0")
            curr = fields.get("MPTAmount", "0")
            try:
                return float(curr) - float(prev)
            except (TypeError, ValueError):
                pass
    return 0.0


def _parse_shares_burned(result: dict) -> float:
    """Extract MPToken shares burned from VaultWithdraw metadata."""
    for node in result.get("meta", {}).get("AffectedNodes", []):
        modified = node.get("ModifiedNode", {})
        if modified.get("LedgerEntryType") == "MPToken":
            fields = modified.get("FinalFields", {})
            prev = (modified.get("PreviousFields") or {}).get("MPTAmount", "0")
            curr = fields.get("MPTAmount", "0")
            try:
                delta = float(prev) - float(curr)
                return max(0.0, delta)
            except (TypeError, ValueError):
                pass
    return 0.0
