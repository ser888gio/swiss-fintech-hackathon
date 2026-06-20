# Connecting to real XRPL (Testnet / Devnet)

By default the API runs with `USE_MOCK_XRPL=true` — the full workflow
(auto-settle → lock → approve → release) runs offline with deterministic fake tx
hashes. This guide flips it to a real network.

> **Run this where the network is open.** Claude Code on the web blocks the XRPL
> endpoints via its egress allowlist. Run the API/script on your laptop (or
> Railway), or add `s.altnet.rippletest.net`, `s.devnet.rippletest.net`, and
> `faucet.altnet.rippletest.net` to the environment's egress settings.

## 1. Pick a network

| Network | `XRPL_ENDPOINT` | Use it for |
| --- | --- | --- |
| **Testnet** | `wss://s.altnet.rippletest.net:51233` | Stable; native XRP + Escrow. Best first target. |
| **Devnet** | `wss://s.devnet.rippletest.net:51233` | Newest amendments first — use if Credentials (XLS-70) or TokenEscrow (XLS-85) aren't enabled on Testnet yet. |

Amendment availability changes over time — check the explorer's *Amendments* page
for your network before relying on Credentials / TokenEscrow.

## 2. Fund wallets (faucet)

Use the included smoke script (preferred) or the Node funder.

```bash
# From apps/api, with deps installed (pip install -r requirements.txt):
python scripts/smoke_xrpl.py fund            # creates + funds a wallet; seed is written to root .env
```

The command writes the treasury seed directly to the ignored root `.env` and
prints only the public address. Use separate, isolated faucet-funded accounts
for receivers and credential issuers; never copy a seed into chat or logs.

## 3. Configure the root `.env`

```bash
USE_MOCK_XRPL=false
XRPL_ENDPOINT=wss://s.altnet.rippletest.net:51233
XRPL_NETWORK=xrpl:1
TREASURY_WALLET_SEED=sEd...          # the agent's funded wallet
TOKEN_CURRENCY=XRP                   # start with XRP (step 4)
FIREFLY_PUBLIC_KEY=<hex>             # npm run keygen --workspace apps/firefly-bridge
```

## 4. First end-to-end test — use XRP

`TOKEN_CURRENCY=XRP` avoids trust lines and uses **native Escrow** for the locked
path — both work on Testnet today.

```bash
# Check connectivity + treasury balance
python scripts/smoke_xrpl.py status

# Send a real test payment (XRP) from the treasury
python scripts/smoke_xrpl.py pay <destination-address> 1
```

Then drive the full agent flow via the API:

```bash
uvicorn app.main:app --reload --port 8000
# POST /payments with a small amount  -> direct Payment, auto-settled
# POST /payments over POLICY_THRESHOLD_USD -> EscrowCreate, then release after a
#   verified Firefly signature (EscrowFinish)
```

Each response carries `txHash` + `explorerUrl`. Open it on
`https://testnet.xrpl.org/transactions/<hash>` and confirm `tesSUCCESS`.

## 5. Issued token (USD IOU) — extra setup

To set `TOKEN_CURRENCY=USD`:

1. `TOKEN_ISSUER_ADDRESS=r...` — your issuer wallet.
2. The **receiver** needs a `TrustSet` trust line to that issuer for `USD`.
3. The **treasury** must already hold the USD IOU (issuer pays it some) to spend.
4. Locking an **issued token** in escrow needs **TokenEscrow (XLS-85)** enabled —
   if it isn't on your network, keep the locked path on XRP.

Cross-currency note: `SendMax` + `Paths` are only attached when routing finds a
real cross-currency path (a same-asset payment with a redundant `SendMax` is
rejected as `temREDUNDANT`).

## 5a. x402 RLUSD on Testnet

The ARS x402 flow uses the official Testnet RLUSD issuer and submits the
`Payment` from the Python API with `xrpl-py`. Prepare the treasury account before
turning real mode on:

```bash
# Root .env (never commit the seed)
USE_MOCK_XRPL=false
XRPL_ENDPOINT=wss://s.altnet.rippletest.net:51233
TOKEN_ISSUER_ADDRESS=rQhWct2fv4Vc4KRjRgMrxa8xPN9Zx9iLKV
TOKEN_CURRENCY=RLUSD
TREASURY_WALLET_SEED=sEd...
X402_FACILITATOR_URL=https://xrpl-facilitator-testnet.t54.ai
X402_ALLOWED_FACILITATORS=https://xrpl-facilitator-testnet.t54.ai

# From apps/api
python scripts/smoke_xrpl.py fund
python scripts/smoke_xrpl.py trustset RLUSD rQhWct2fv4Vc4KRjRgMrxa8xPN9Zx9iLKV
```

Send enough Testnet XRP to the treasury for its account reserve, trust-line
owner reserve, and transaction fees. Then claim Testnet RLUSD for the treasury
address at [tryrlusd.com](https://tryrlusd.com) and verify both balances:

```bash
python scripts/smoke_xrpl.py status
# Token : <positive value> RLUSD (trust line present)
```

The t54 facilitator is not itself a paid resource. For a self-contained local
proof, enable the API's merchant endpoint and give it a Testnet account that has
an RLUSD trust line:

```bash
X402_DEMO_ENABLED=true
X402_DEMO_PAY_TO=r...
X402_DEMO_PRICE=1.000000
VITE_X402_SERVICE_URL=http://localhost:8000/treasury/x402/demo-resource
```

The demo endpoint returns 402, then independently queries Testnet before
releasing content. It verifies `tesSUCCESS`, validation, payer, payee, exact
RLUSD issuer/currency/amount, source tag, and invoice memo. For an external
merchant, configure `VITE_X402_SERVICE_URL` to a compatible protected resource;
the retired t54 `/demo-resource` URL returns 404. The
[t54 FastAPI merchant guide](https://xrpl-x402.t54.ai/docs/merchant-guides/fastapi)
shows how to run a local `/hello` endpoint.

Finally, start the API and trigger the ARS x402 payment. A successful real
settlement returns a non-null `explorerUrl` under
`https://testnet.xrpl.org/transactions/<hash>`; open it and confirm the validated
result is `tesSUCCESS`. If the paid service does not return HTTP 402, the API
returns a clear upstream error and does not present a simulated payment.

### Verified Testnet evidence (2026-06-20)

- Guardrails: G1 KYA passed using an accepted on-ledger credential; G4 scope passed.
- Settlement: `1.000000 RLUSD`, validated `tesSUCCESS`.
- Transaction: [`64A147F9…D8126`](https://testnet.xrpl.org/transactions/64A147F973410A467098BBF3A5C2464D4B928D87842B63401A214201246D8126).
- Merchant proof replay returned HTTP 200 only after the endpoint independently
  verified the transaction fields and invoice memo against Testnet.

## 6. Credentials (XLS-70) KYC on a real network

```bash
CREDENTIAL_KYC_ENABLED=true
CREDENTIAL_TYPE=KYC
CREDENTIAL_ISSUER_SEED=sEd...        # issuer that signs CredentialCreate
CREDENTIAL_ISSUER_ADDRESS=r...       # verified against; same issuer
CREDENTIAL_SUBJECT_SEED=sEd...       # subject that signs CredentialAccept (demo only)
```

Flow:

1. `credentials.issue_credential(subject)` → `CredentialCreate`.
2. The **subject** must `CredentialAccept` it (their own signed tx) — `verify_kyc`
   only counts *accepted*, non-expired credentials.
3. A payment to a credentialed subject auto-settles; a payment to an
   un-credentialed subject is escalated to hardware approval **by the policy
   engine**, never the LLM.

Requires the Credentials amendment. If `CredentialCreate` fails with an
amendment/unknown-transaction error, switch `XRPL_ENDPOINT` to Devnet.

### Credential-issuing agent (run the full lifecycle from the API/UI)

A second agent (`app/agents/credential_agent.py`, routes under `/credentials`,
UI tab **Credentials**) drives issue → accept → verify and narrates each step.
Whether a subject may be issued a credential is a **deterministic sanctions
screen** inside the agent — never the LLM.

To prove it on Testnet (with `USE_MOCK_XRPL=false` and the seeds above):

```bash
# 1. Issue (treasury signs CredentialCreate) — returns a record with txHash
curl -X POST $API/credentials -H 'content-type: application/json' \
  -d '{"subject":"r<subject>","subjectName":"Vendor Alpha","credentialType":"KYC","uri":"https://kyc.example/vc/1"}'

# 2. Accept (subject signs CredentialAccept, using CREDENTIAL_SUBJECT_SEED)
curl -X POST $API/credentials/<recordId>/accept

# 3. Verify (fresh on-ledger lookup; only accepted, non-expired credentials pass)
curl -X POST $API/credentials/<recordId>/verify
```

A real submission returns `txHash` + `explorerUrl` on the create and accept
steps. A payment to that subject then auto-settles (step 6 above), while an
un-credentialed subject escalates — proving the credential gate end-to-end.

## 7. Verify

- Real submissions return `txHash` + `explorerUrl`.
- The execution tool reads `meta.delivered_amount` (not `Amount`), so a partial
  or zero delivery is reported as `failed`, not a false success.

**Suggested path:** prove the XRP loop on Testnet (step 4) first, then layer in the
USD token (5) and Credentials (6), moving to Devnet only if an amendment is
missing.
