# firefly-bridge — local hardware bridge

Runs **only on the operator's machine.** It owns the connection to the Firefly
device (github.com/firefly) and exposes a localhost endpoint the dashboard calls
to request an approval signature. The Railway API never talks to hardware
directly — the signature travels browser → API, and the API verifies it before
releasing funds.

## How it works

1. The dashboard fetches the approval challenge (a digest) from the API.
2. It POSTs `{ paymentId, digest }` to `http://localhost:4747/sign`.
3. The Firefly **displays the request and waits for the physical button press**,
   then returns a secp256k1 signature.
4. The dashboard sends the signature to the API, which verifies it against the
   registered public key and submits EscrowFinish.

During development a `MockFireflyDevice` signs with a local key so the whole flow
works without hardware. Swap it for a serial implementation that drives the real
board (see `src/device.ts`).

## Setup

```bash
npm install                                   # from repo root
npm run keygen --workspace apps/firefly-bridge
```

Copy the printed values: `FIREFLY_MOCK_PRIVATE_KEY` into this bridge's env,
`FIREFLY_PUBLIC_KEY` into the API's env. Then:

```bash
npm run dev:bridge        # http://localhost:4747
```

## Byte formats (must match the API verifier)

- Signature: 65 bytes — `r(32) || s(32) || recovery(1)`, hex.
- Public key: 64 bytes — uncompressed secp256k1 without the `0x04` prefix, hex.

These match `eth_keys` as used in `apps/api/app/tools/firefly.py`. When wiring the
real Firefly, confirm its output matches these or adapt the verifier.
