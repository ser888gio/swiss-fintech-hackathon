# Demo script (target: under 3 minutes)

The physical Firefly button press is the money shot. Choreograph it.

## Setup before judges arrive

- API + web deployed on Railway, reachable over the public URL.
- Firefly bridge running on the demo laptop; Firefly device plugged in and
  unlocked; `FIREFLY_PUBLIC_KEY` registered in the API env.
- A funded testnet treasury wallet; token trust lines set.
- A cached successful run's explorer links open in a backup tab (in case testnet
  is flaky). Backup screencap recorded.

## The five beats

1. **Open the dashboard.** Invoice queue on the left, live agent log streaming on
   the right. "This agent runs our cross-border payments on XRPL."

2. **$500 vendor invoice.** Click pay. The agent narrates: routes via
   `ripple_path_find`, compliance clears (AML 12/100), policy says auto-settle.
   Direct Payment lands in ~4s. **Show the testnet explorer link.**

3. **$50,000 invoice.** Click pay. The agent flags it — over the $10k threshold.
   Funds are **locked on-chain via escrow**. A pending-approval card appears.
   "The agent cannot release this. Nobody can — without the device."

4. **Pick up the Firefly. The device shows the request. Press the button.** The
   signature verifies on screen → EscrowFinish submitted → settled in <5s. This
   is the beat to slow down for.

5. **Proof.** Open the testnet explorer: both transactions live on-chain. Open
   the audit log: every decision explained in plain language — route, compliance
   score, the rule that fired, the signature that released it.

## The two lines to land

1. "The AI decides nothing about money — code does. The AI explains."
2. "No one, including the agent, can move a large payment without this device in
   my hand."

## If something breaks

- Testnet slow → switch to the cached explorer tab, keep narrating.
- Firefly won't connect → be honest, demo the device signing the challenge
  standalone, fall back to the software release key, explain the integration
  status. Do not pretend.
