import cors from "cors";
import express from "express";
import type { BridgeSignRequest, BridgeSignResponse } from "@treasury/shared";

import { SerialFireflyDevice } from "./device.js";
import type { FireflyDevice } from "./device.js";

const PORT = Number(process.env.BRIDGE_PORT ?? 4747);
const DEVICE_PATH = process.env.FIREFLY_DEVICE_PATH;
const DEVICE_PUBLIC_KEY = process.env.FIREFLY_PUBLIC_KEY;

if (!DEVICE_PATH) {
  console.error(
    "[firefly] FIREFLY_DEVICE_PATH is not set. " +
    "Connect the Firefly Pixie and set FIREFLY_DEVICE_PATH (e.g. COM3 or /dev/ttyACM0)."
  );
  process.exit(1);
}
if (!DEVICE_PUBLIC_KEY) {
  console.error(
    "[firefly] FIREFLY_PUBLIC_KEY is not set. " +
    "Run `npx tsx src/keygen.ts` to generate a keypair, flash the private key onto the " +
    "device, and set FIREFLY_PUBLIC_KEY in the environment."
  );
  process.exit(1);
}

const device: FireflyDevice = new SerialFireflyDevice(DEVICE_PATH, DEVICE_PUBLIC_KEY);
console.log(`[firefly] Using real Firefly Pixie at ${DEVICE_PATH}`);

const app = express();
app.use(cors());
app.use(express.json());

app.get("/health", (_req, res) => {
  res.json({ status: "ok", publicKey: device.publicKeyHex() });
});

app.post("/sign", async (req, res) => {
  const body = req.body as BridgeSignRequest;
  if (
    !body?.paymentId || body?.amount == null || !body?.currency ||
    !body?.dest || !body?.network || !body?.owner ||
    body?.escrowSequence == null || !body?.escrowCreateTxHash
  ) {
    res.status(400).json({
      error: "paymentId, amount, currency, dest, network, owner, escrowSequence, and escrowCreateTxHash are required",
    });
    return;
  }

  console.log(`[firefly] ┌─ APPROVE REQUEST ─────────────────────────────────┐`);
  console.log(`[firefly] │  Network:    ${body.network}`);
  console.log(`[firefly] │  Amount:     ${body.amount.toFixed(2)} ${body.currency}`);
  console.log(`[firefly] │  To:         ${body.dest}`);
  console.log(`[firefly] │  Owner:      ${body.owner}`);
  console.log(`[firefly] │  Escrow seq: ${body.escrowSequence}`);
  console.log(`[firefly] │  Escrow tx:  ${body.escrowCreateTxHash.slice(0, 16)}…`);
  console.log(`[firefly] │  Reference:  ${body.reference ?? "(none)"}`);
  console.log(`[firefly] │  Payment:    ${body.paymentId}`);
  console.log(`[firefly] └───────────────────────────────────────────────────┘`);
  console.log(`[firefly] Awaiting button press…`);

  try {
    const signed = await device.sign(body);
    const response: BridgeSignResponse = {
      paymentId: body.paymentId,
      signature: signed.signature,
      publicKey: signed.publicKey,
    };
    console.log(`[firefly] ✓ Signed payment ${body.paymentId}`);
    res.json(response);
  } catch (cause) {
    console.error(`[firefly] signing failed: ${String(cause)}`);
    res.status(500).json({ error: String(cause) });
  }
});

app.listen(PORT, () => {
  console.log(`Firefly bridge listening on http://localhost:${PORT}`);
  console.log(`Device public key: ${device.publicKeyHex()}`);
});
