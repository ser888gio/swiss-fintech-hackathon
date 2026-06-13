# SwissHacks 2026 — Preparation Plan
## Autonomous Treasury Agent with Firefly Hardware Veto (XRPL)

**Event:** SwissHacks 2026, Zurich, June 19–21 · 48 hours
**Challenge:** Ripple — Future of Finance on XRPL · Track: AI Agents for Finance

> This is the source-of-truth plan. Architecture decisions here are **locked** —
> do not relitigate at the hackathon. See `challenge.md` for the official brief,
> `architecture.md` for the system design, `demo-script.md` and `judging.md` for
> the pitch.

---

## 1. The pitch in one paragraph

A treasury agent that runs corporate cross-border payments on XRPL: it routes,
screens, and explains every payment. Small/low-risk payments settle autonomously
in seconds. Large or flagged payments are locked on-chain and can only be
released by a physical Firefly hardware approval. The LLM orchestrates and
narrates; deterministic code enforces policy and signing. *"The agent handles the
routine. The human controls what matters."*

---

## 2. Locked architecture decisions

| Decision | Choice | Rationale |
|---|---|---|
| Deployment | Railway: web (dashboard) + API (agents, XRPL, policy) + Postgres | Simple, demo-stable |
| Hardware | Firefly stays **local**, bridged via browser/local bridge | Never connect Railway → hardware directly |
| Agent design | One backend workflow; "agents" presented in UI, implemented as deterministic tools | Saves time, same judge impression |
| LLM role | Orchestrates + explains only | **Policy and signing rules enforced in code, never by the LLM** |
| Approval | Must be cryptographically meaningful (signed payload), not a UI button | Otherwise the core innovation is fake |
| Claims discipline | No "zero intermediaries" — fiat on/off ramps exist | Avoids judge pushback |

## 2a. Track strategy

- **Primary: AI Agents for Finance** — the treasury agent itself.
- **Secondary: Cross-border payments & FX** — routing/RLUSD settlement layer.
- **Optional bonus: Credit & Lending (XLS-66)** — *idle treasury sweep* into a
  Single Asset Vault (XLS-65). One `VaultDeposit`/`VaultWithdraw` pair, narrated
  by the agent. Only after the hour-32 gate; likely requires Devnet.

Prepare the 30-second mainnet answer (viability = 40% of score): production swaps
testnet for mainnet, mock compliance for a real screening provider, self-issued
IOU for real RLUSD, the local Firefly bridge for an HSM/custody signer. The
architecture is unchanged.

---

## 3. Team decisions

1. Hardware veto mechanism: conditional escrow vs. XRPL multisig vs.
   Firefly-signed approval payload verified by backend?
2. Fallback if Firefly integration stalls (deadline hour 22 — see risk plan).
3. Real RLUSD vs. mock issued USD token on testnet?
4. Postgres audit schema: minimum = payment intent, route quote, compliance
   result + score, policy decision + rule fired, approval payload + signature,
   tx hash, timestamps.
5. Ownership: frontend / backend / XRPL / Firefly / pitch — assign names.
6. Minimum demo that must work by hour 32 (items 1–3 + 5–6 of the MVP ladder).

**Resolved by research (June 2026):**
- ✅ **TokenEscrow (XLS-85) is live** — activated on XRPL mainnet Feb 12, 2026, so
  it's on testnet too. Escrow now works for IOUs and MPTokens, including RLUSD.
  **Caveat:** the token's *issuer* must have enabled escrow —
  `asfAllowTrustLineLocking` (AccountSet SetFlag 17) for IOUs, or
  `tfMPTCanEscrow` for MPTs. If the testnet RLUSD issuer hasn't set this,
  fallback: issue our own mock USD IOU and set the flag ourselves.
- ✅ **XLS-65 (Single Asset Vault) and XLS-66 (Lending)** are available on Devnet
  and were in validator voting for mainnet as of spring 2026. Testing UI at
  tests.xrpl-commons.org/lending.

**Questions for Ripple mentors (day 1 morning):**
1. Testnet vs. Devnet — are XLS-65/66 enabled on Testnet yet, or Devnet only?
2. Current RLUSD testnet/devnet issuer address — has it enabled trust-line
   locking (escrow flag)?
3. Judging priority among TokenEscrow / multisig / MPTokens / pathfinding?
4. Preferred compliance metadata channel: memos, MPTokens, credentials, or
   off-chain hash anchored on-chain?
5. Would judges value Firefly as physical approval even if it doesn't natively
   sign XRPL transactions?
6. Is a small XLS-66 add-on (idle treasury → vault yield) worth the credit-track
   bonus, or stay focused?

---

## 4. Agents / tools (final list)

| Component | Type | Responsibility |
|---|---|---|
| **Treasury Orchestrator** | LLM loop | Receives payment intent, calls tools, narrates decisions |
| **Routing Tool** (`get_fx_path`) | Deterministic | Frankfurter FX quote + `ripple_path_find`, cheapest path summary |
| **Compliance Tool** (`check_compliance`) | Deterministic (mock OK) | Sanctions/KYC screen + AML score 0–100 + explanation |
| **Policy Engine** | Deterministic, code-enforced | Threshold + risk-score decision: auto vs. escalate. NOT the LLM's call |
| **Execution Tool** | Deterministic | Direct RLUSD Payment or escrow/locked tx |
| **Firefly Approval Tool** | Deterministic | Generates approval payload, verifies Firefly signature, triggers release |
| **Audit Tool** | LLM-assisted | Writes human-readable explanation of each decision to Postgres |

Policy logic (in code):
```python
THRESHOLD_USD = 10_000
COMPLIANCE_FLAG_SCORE = 60
requires_approval = amount_usd > THRESHOLD_USD or aml_score > COMPLIANCE_FLAG_SCORE
```

---

## 5. Hardware veto — three options, pick one

| Option | How it works | Pros | Cons |
|---|---|---|---|
| **A. Conditional escrow** | EscrowCreate with a PREIMAGE-SHA-256 condition; Firefly holds/derives the preimage; EscrowFinish supplies fulfillment | On-chain enforced; strongest story; token escrow live (XLS-85) | Issuer escrow flag dependency; condition plumbing fiddly |
| **B. XRPL multisig** | Treasury account requires agent key + hardware key signatures for large tx | Native XRPL, judges love it | Firefly likely can't sign XRPL tx natively |
| **C. Firefly-signed approval payload** | Firefly signs a challenge (payment hash); backend verifies, then co-signs/finishes | Easiest to ship; cryptographically real | Release key in backend; weaker on-chain story — mitigate by combining with escrow |

**Recommended:** C as the baseline (ship by hour 22), upgrade to A or B if mentors
confirm feasibility. C + XRP-denominated escrow is a credible hybrid: funds are
genuinely locked on-chain, release gated by verifying the Firefly signature.

---

## 6. MVP ladder (build in this order)

1. **Hour 0–2:** Testnet wallets funded, xrpl round-trip works, Railway skeleton deployed.
2. **Hour 2–10:** Routing + Compliance tools return clean JSON; orchestrator loop calls them.
3. **Hour 10–16:** Small payment auto-settles end-to-end; explorer link visible ← *first demo-able moment*.
4. **Hour 16–22:** Escrow/lock path for large payments; pending-approval queue in DB.
5. **Hour 16–22 (parallel):** Firefly bridge: challenge → button press → signature → verification.
6. **Hour 22–32:** Wire approval to escrow release; full happy path works.
7. **Hour 32–40:** Dashboard polish: invoice list, live agent log, pending queue, tx history, audit explanations.
8. **Hour 40–44:** Edge cases, demo rehearsal on stable data, explorer verification.
9. **Hour 44–48:** Pitch prep, judging Q&A drills.

**Hour-32 gate (must work):** dashboard + small auto-payment on XRPL + large
payment pending + *any* approval mechanism releasing it + explorer proof. If
Firefly isn't integrated by hour 22, fall back to a locally-signed software key
presented honestly, or demo Firefly signing the challenge standalone.

---

## 7. Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Testnet RLUSD issuer hasn't enabled escrow flag | Medium | XLS-85 live; if RLUSD lacks `asfAllowTrustLineLocking`, self-issue mock USD IOU with SetFlag 17 |
| Firefly integration takes too long | Medium | Hard deadline hour 22; fallback above |
| RLUSD testnet issuer unclear / no faucet | Medium | Self-issued mock USD IOU from a wallet we control |
| Testnet flaky during demo | Low–medium | Record a backup screencap; cache a successful run's explorer links |
| LLM orchestrator misbehaves live | Medium | Policy in code → worst case is bad narration; pre-can demo prompts |
| Demo WiFi issues | Always | Phone hotspot; local fallback for dashboard |

---

## 8. Demo script (5 steps)

1. Dashboard open: invoice queue, agent log streaming.
2. **$500 vendor invoice** → agent routes, compliance clears (AML 12/100), settles
   in ~4s — show explorer link.
3. **$50,000 invoice** → agent flags (over threshold), funds locked,
   pending-approval card appears.
4. **Pick up Firefly. Press button.** Signature verified on screen → release tx
   submitted → settled in <5s.
5. Open testnet explorer: both transactions live on-chain. Show audit log: every
   decision explained in plain language.

Practice until under 3 minutes. The physical button press is the money shot.

---

## 9. Judging map

| Criterion | Weight | How we score |
|---|---|---|
| Viability & feasibility | 40% | Everything live on testnet, explorer proof, deployed on Railway (not localhost) |
| Technical XRPL use | 25% | Escrow (or multisig), RLUSD/issued token, ripple_path_find, compliance metadata |
| Innovation | 20% | Physical hardware veto + code-enforced policy boundary |
| Design & UX | 15% | Live agent log, pending-approval queue, plain-language audit trail |

Two lines to land: (1) "The AI decides nothing about money — code does. The AI
explains." (2) "No one, including the agent, can move a large payment without this
device in my hand."

---

## 10. Pre-hackathon checklist

- [ ] Railway project created; web + API + Postgres provisioned; CI deploy works
- [ ] Testnet wallets generated and funded; seeds stored safely (not in repo)
- [ ] xrpl Payment round-trip tested on testnet
- [ ] Frankfurter API call tested
- [ ] Firefly: confirm what it can sign (curve, payload format); bridge spike
- [ ] EscrowCreate/EscrowFinish tested with XRP (escrow plumbing known-good)
- [ ] Mock sanctions list + AML scoring function drafted
- [ ] Dashboard skeleton (React) with fake data, deployable
- [ ] Pitch deck skeleton: problem → demo → architecture → why XRPL
- [ ] Team roles assigned (§3 item 5)
