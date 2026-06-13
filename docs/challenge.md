# Challenge — Ripple: Future of Finance on XRPL

Official challenge text (SwissHacks 2026):

> **CHALLENGE 1: Ripple — Future of Finance on XRPL**
>
> Build an institutional DeFi prototype on XRPL Devnet or Testnet across one or
> more of three tracks: **cross-border payments and FX**, **credit and lending**,
> or **AI agents for finance**. The idea is to fix the slow, costly plumbing of
> institutional finance using XRPL primitives like the **Lending Protocol
> (XLS-66)**, **Single Asset Vaults (XLS-65)**, **MPTokens**, **TokenEscrow**, and
> **RLUSD**. Solutions should hit a real institutional pain point and show a
> believable path to mainnet. Judging leans heavily on **viability and
> feasibility (40%)** and **technical use of XRPL features (25%)**.

## Our positioning against the tracks

- **Primary — AI Agents for Finance:** the treasury agent itself.
- **Secondary — Cross-border payments & FX:** the routing / RLUSD settlement
  layer (covered for free by the agent's execution path).
- **Optional bonus — Credit & Lending (XLS-66):** one stretch feature, the *idle
  treasury sweep* — deposit excess RLUSD into a Single Asset Vault (XLS-65) for
  yield, withdraw when liquidity is needed. Build only after the hour-32 gate.

## The institutional pain point

Corporate cross-border treasury operations are slow, opaque, and bottlenecked on
human approval for every payment regardless of size. We let routine payments
settle autonomously in seconds while keeping a **physical, cryptographic human
veto** on the payments that matter — without trusting an LLM to move money.

## Believable path to mainnet (30-second answer)

Production swaps: testnet → mainnet; mock compliance → a real screening provider
(Chainalysis/Elliptic-style API); self-issued IOU → real RLUSD; the local Firefly
bridge → an HSM or institutional custody signer. The architecture —
**policy-in-code, on-chain escrow, hardware approval** — is unchanged.
