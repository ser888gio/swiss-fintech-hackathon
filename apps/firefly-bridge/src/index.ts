import cors from "cors";
import express from "express";
import type { BridgeSignRequest, BridgeSignResponse } from "@treasury/shared";

import { MockFireflyDevice } from "./device.js";

const PORT = Number(process.env.BRIDGE_PORT ?? 4747);
const MOCK_KEY = process.env.FIREFLY_MOCK_PRIVATE_KEY;

if (!MOCK_KEY) {
  throw new Error(
    "FIREFLY_MOCK_PRIVATE_KEY is not set. Run `npm run keygen --workspace apps/firefly-bridge` " +
      "and put the private key here and the public key in the API's FIREFLY_PUBLIC_KEY.",
  );
}

const device = new MockFireflyDevice(MOCK_KEY);
const app = express();
app.use(cors());
app.use(express.json());

app.get("/health", (_req, res) => {
  res.json({ status: "ok", publicKey: device.publicKeyHex() });
});

app.post("/sign", async (req, res) => {
  const body = req.body as BridgeSignRequest;
  if (!body?.paymentId || !body?.amount || !body?.currency || !body?.dest) {
    res.status(400).json({ error: "paymentId, amount, currency, and dest are required" });
    return;
  }
  // Print what the device is being asked to approve — stand-in for the hardware screen.
  console.log(
    `[firefly] ┌─ APPROVE REQUEST ─────────────────────────────────┐`,
  );
  console.log(`[firefly] │  Amount:    ${body.amount.toFixed(2)} ${body.currency}`);
  console.log(`[firefly] │  To:        ${body.dest}`);
  console.log(`[firefly] │  Reference: ${body.reference ?? "(none)"}`);
  console.log(`[firefly] │  Payment:   ${body.paymentId}`);
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
    res.status(500).json({ error: "signing failed" });
  }
});

app.listen(PORT, () => {
  console.log(`Firefly bridge listening on http://localhost:${PORT}`);
  console.log(`Device public key: ${device.publicKeyHex()}`);
});
