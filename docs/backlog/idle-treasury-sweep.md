# Backlog: Idle Treasury Sweep (XLS-65 / XLS-66)

**Status:** Spec only — not implemented. Build only after the hour-32 gate is
fully passed and features A–C are solid.

## Concept

Idle RLUSD in the treasury wallet earns nothing while awaiting the next batch of
payroll/vendor payments. The agent narrates an automatic sweep: excess balance
deposits into a Single Asset Vault (XLS-65) for yield, then withdraws to fund
upcoming payments.

**Pitch line:** "While you slept, the treasury earned yield, then pulled it back
to cover Friday's payroll — narrated, verified, no human needed for routine
sweeps."

## XRPL primitives

- **XLS-65 Single Asset Vault** — `VaultDeposit` / `VaultWithdraw` transactions.
- **XLS-66 Lending Protocol** — the vault lends deposited assets; depositors
  earn yield. As of spring 2026 both are on Devnet; verify Testnet availability
  with Ripple mentors on day 1.

**Testing UI:** tests.xrpl-commons.org/lending (Devnet).

## Architecture sketch

```
apps/api/app/tools/vault.py
  deposit(amount: float, currency: str) -> VaultResult
  withdraw(amount: float, currency: str) -> VaultResult
  balance() -> float
```

Both functions follow the same mockable pattern as `execution.py`:
`if settings.use_mock_xrpl: return deterministic fake result`.

The orchestrator (or a scheduled job) triggers sweeps:

```python
idle = vault_balance.get() - reserve_minimum
if idle > SWEEP_THRESHOLD:
    vault.deposit(idle, currency)
    _log("Swept idle RLUSD into vault for yield.")
```

**Policy guardrail (non-negotiable):** sweep amounts are bounded by a
`SWEEP_THRESHOLD` constant in `app/policy/engine.py`. Any withdrawal that
exceeds `THRESHOLD_USD` must go through the existing escrow + Firefly approval
path — same as any other large payment. The agent narrates; code decides.

## Dashboard tile

- Current vault position and yield accrued.
- Last sweep timestamp and amount.
- Projected interest at current rate.
- "Withdraw to cover payment" button (triggers withdrawal, potentially escalating
  to Firefly if over threshold).

## Risks

| Risk | Mitigation |
|---|---|
| XLS-65/66 Devnet only, not Testnet | Confirm with Ripple mentors day 1; demo on Devnet separately if needed |
| Time | Hard cut if not started by hour 36 |
| Network split (rest of demo on Testnet) | Be honest in the pitch: "vault demo on Devnet, core demo on Testnet" |

## Path to mainnet

The vault primitives are unchanged (XLS-65/66 → mainnet when activated). The
sweep policy bounds and the Firefly withdrawal gate are already mainnet-ready
(same code). Replace mock RLUSD with real RLUSD; add a yield-rate oracle feed.
