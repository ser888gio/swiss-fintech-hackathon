# Judging map

| Criterion | Weight | How we score it |
|---|---|---|
| **Viability & feasibility** | 40% | Everything live on XRPL **testnet** with explorer proof; deployed on **Railway**, not localhost; a crisp 30-second path-to-mainnet answer. |
| **Technical XRPL use** | 25% | TokenEscrow (XLS-85) for the locked large payments, RLUSD or self-issued IOU, `ripple_path_find` for routing, compliance metadata on-chain (memos/MPTokens). |
| **Innovation** | 20% | Physical hardware veto + a **code-enforced policy boundary** — the LLM literally cannot move money. |
| **Design & UX** | 15% | Live agent log, pending-approval queue, plain-language audit trail. |

## Path to mainnet (rehearse this)

Production swaps testnet → mainnet; mock compliance → a real screening provider
(Chainalysis/Elliptic-style); self-issued IOU → real RLUSD; the local Firefly
bridge → an HSM or institutional custody signer. The architecture —
**policy-in-code, on-chain escrow, hardware approval** — does not change. That is
the feasibility argument.

## Claims discipline

- Do **not** say "zero intermediaries" — fiat on/off ramps exist.
- Do **not** imply the LLM is trusted with money — it is explicitly not.
- Do say: routine payments settle autonomously; the payments that matter require
  a cryptographic human approval that nobody can bypass.

## Anticipated judge questions

- *"What stops the agent from draining the treasury?"* → Policy is deterministic
  code with unit tests; large payments are escrow-locked and need a verified
  hardware signature; sanctioned payments are **blocked in code — hardware cannot
  override them**. Show `apps/api/app/policy/engine.py`. Better yet: demo the
  sanctions refusal live (beat 3).
- *"Is the approval real or a button in the UI?"* → It is a secp256k1 signature
  from the Firefly, verified server-side against a pre-registered public key
  before EscrowFinish. The bridge displays the *actual* payment (WYSIWYS) — not a
  server-supplied hash. And we prove the binding live: hit the Tamper button →
  same signature, altered amount → 403 rejected (beat 6).
- *"Can a rogue LLM approve its own payments?"* → No. The `release_payment`
  function in the orchestrator is synchronous deterministic code; it requires a
  valid secp256k1 signature from the registered Firefly public key. The LLM has
  no access to the private key and cannot produce that signature.
- *"Why XRPL?"* → Native escrow (XLS-85), fast cheap settlement, RLUSD,
  pathfinding for FX — the primitives the use case needs, on-ledger.
- *"Path to mainnet?"* → The 30-second answer above. Architecture is unchanged;
  swap testnet→mainnet, mock compliance→Chainalysis/Elliptic, self-issued
  IOU→real RLUSD, local Firefly bridge→HSM/custody signer.
