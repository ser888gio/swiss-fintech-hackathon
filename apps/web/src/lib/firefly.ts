import type { BridgeSignRequest, BridgeSignResponse } from "@treasury/shared";

// The bridge runs on the operator's local machine and owns the USB connection to
// the Firefly device. The browser asks it to sign; the device shows the request
// and waits for a physical button press before returning a signature.
const BRIDGE_URL = import.meta.env.VITE_BRIDGE_BASE_URL ?? "http://localhost:4747";

export async function signOnFirefly(req: BridgeSignRequest): Promise<BridgeSignResponse> {
  const response = await fetch(`${BRIDGE_URL}/sign`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!response.ok) {
    throw new Error(`Firefly bridge error: ${response.status} ${await response.text()}`);
  }
  return response.json() as Promise<BridgeSignResponse>;
}
