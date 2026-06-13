# Demo script (target: under 4 minutes)

The physical Firefly button press is the money shot. The sanctions block and the
tamper rejection are the proof shots. Choreograph all three.

## Setup before judges arrive

- API + web deployed on Railway, reachable over the public URL. `DEMO_MODE=true`
  set in Railway env so the Tamper button is visible.
- Firefly bridge running on the demo laptop; Firefly device plugged in and
  unlocked; `FIREFLY_PUBLIC_KEY` registered in the API env.
- A funded testnet treasury wallet; token trust lines set.
- A cached successful run's explorer links open in a backup tab (in case testnet
  is flaky). Backup screencap recorded.

## The seven beats

1. **Open the dashboard.** Invoice queue, live agent log streaming. "This agent
   runs our cross-border payments on XRPL."

2. **$500 vendor invoice.** Click pay. Agent narrates: routes via
   `ripple_path_find`, compliance clears (AML 12/100), policy says auto-settle.
   Direct Payment lands in ~4s. **Show the testnet explorer link.**

3. **Sanctioned counterparty.** Submit an invoice to `ACME-SHELL-CO`. Card turns
   red: **REFUSED — counterparty on sanctions list**. "Notice it did *not* go to
   the approval queue. The hardware cannot approve a sanctions block. This is
   refused in code, period."

4. **$50,000 invoice.** Click pay. Agent flags it — over the $10k threshold.
   Funds **locked on-chain via escrow**. Pending-approval card appears.
   "The agent cannot release this. Nobody can — without the device."

5. **Pick up the Firefly. The bridge terminal shows the actual payment — amount,
   payee, reference — not a hash. Press the button.** Signature verifies on
   screen → EscrowFinish submitted → settled in <5s. Slow down here. "The device
   signed *5,000 RLUSD to Berlin GmbH* — the real payment. Not a hash."

6. **Tamper & retry (DEMO).** Click the purple button on the just-released card.
   Big red: **SIGNATURE REJECTED — payment details were altered**. "The signature
   is bound to the exact payment. Change one digit and it's worthless."

7. **Proof.** Open the testnet explorer: both settled transactions on-chain. Click
   "Download audit receipt" on any card — JSON with route, AML score, rule fired,
   Firefly signature, receipt hash. "Hand this to your auditor; they recompute
   the hash and verify nothing was altered."

## The two lines to land

1. "The AI decides nothing about money — code does. The AI explains."
2. "No one, including the agent, can move a large payment without this device in
   my hand — and no one can alter the payment after signing."

## If something breaks

- Testnet slow → switch to the cached explorer tab, keep narrating.
- Firefly won't connect → be honest, demo the bridge terminal output showing the
  approval details, fall back to the software release key, explain integration
  status. Do not pretend.
