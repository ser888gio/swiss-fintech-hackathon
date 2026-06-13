import { sha256 } from "@noble/hashes/sha256";
import { secp256k1 } from "@noble/curves/secp256k1";
import type { BridgeSignRequest } from "@treasury/shared";

// Signature/public-key byte formats are chosen to match the API's verifier
// (eth_keys in apps/api/app/tools/firefly.py):
//   - signature: 65 bytes, r(32) || s(32) || recovery(1), hex. Recovery is
//     returned as 0/1; the Python verifier also normalises 27/28 just in case.
//   - publicKey: 64 bytes, uncompressed without the 0x04 prefix, hex.
export interface SignedApproval {
  signature: string;
  publicKey: string;
}

export interface FireflyDevice {
  /** Display the payment details and sign once the button is pressed. */
  sign(req: BridgeSignRequest): Promise<SignedApproval>;
  publicKeyHex(): string;
}

const PAYLOAD_VERSION = "XRPL_TREASURY_APPROVAL_V1";

/**
 * Canonical payload format — MUST stay identical to Python firefly.py:
 *   f"{PAYLOAD_VERSION}|{network}|{payment_id}|{owner}|{dest}|{currency}|{amount:.2f}|{escrow_sequence}|{escrow_create_tx_hash}"
 *
 * Any change here must be mirrored in apps/api/app/tools/firefly.py.
 */
export function deriveDigest(req: BridgeSignRequest): string {
  const canonical = [
    PAYLOAD_VERSION,
    req.network,
    req.paymentId,
    req.owner,
    req.dest,
    req.currency,
    req.amount.toFixed(2),
    String(req.escrowSequence),
    req.escrowCreateTxHash,
  ].join("|");
  const hash = sha256(new TextEncoder().encode(canonical));
  return Buffer.from(hash).toString("hex");
}

function strip0x(value: string): string {
  return value.startsWith("0x") ? value.slice(2) : value;
}

function uncompressedNoPrefix(privateKey: Uint8Array): string {
  const full = secp256k1.getPublicKey(privateKey, false); // 65 bytes, leading 0x04
  return Buffer.from(full.slice(1)).toString("hex");
}

/**
 * Stand-in for the real Firefly hardware during development. Signs with a local
 * secp256k1 key so the full approve→verify→release flow works offline. Replace
 * with SerialFireflyDevice for hardware demos.
 */
export class MockFireflyDevice implements FireflyDevice {
  private readonly privateKey: Uint8Array;

  constructor(privateKeyHex: string) {
    this.privateKey = Buffer.from(strip0x(privateKeyHex), "hex");
  }

  publicKeyHex(): string {
    return uncompressedNoPrefix(this.privateKey);
  }

  async sign(req: BridgeSignRequest): Promise<SignedApproval> {
    const digestHex = deriveDigest(req);
    const digest = Buffer.from(digestHex, "hex");
    const sig = secp256k1.sign(digest, this.privateKey);
    const signature = Buffer.concat([
      sig.toCompactRawBytes(),
      Buffer.from([sig.recovery]),
    ]).toString("hex");
    return { signature, publicKey: this.publicKeyHex() };
  }
}

/**
 * Real Firefly Pixie hardware via USB serial. The device runs a custom app
 * (apps/firefly-pixie) that displays the payment fields, blocks on the physical
 * OK/Cancel button, and returns a secp256k1 signature over the canonical digest.
 *
 * Protocol (newline-delimited JSON over serial at 115200 baud):
 *   → {"cmd":"sign","digest":"<hex>","display":{amount,currency,dest,network,owner,escrowSequence,escrowTxHash}}
 *   ← {"status":"ok","signature":"<hex>"}  |  {"status":"rejected"}
 *
 * To use: set FIREFLY_DEVICE_PATH (e.g. COM3 on Windows, /dev/ttyACM0 on Linux)
 * and install serialport: npm install serialport --workspace apps/firefly-bridge
 */
export class SerialFireflyDevice implements FireflyDevice {
  private readonly devicePath: string;
  private readonly _publicKeyHex: string;

  constructor(devicePath: string, publicKeyHex: string) {
    this.devicePath = devicePath;
    this._publicKeyHex = strip0x(publicKeyHex);
  }

  publicKeyHex(): string {
    return this._publicKeyHex;
  }

  async sign(req: BridgeSignRequest): Promise<SignedApproval> {
    // Dynamic import via runtime string so tsc doesn't try to resolve the
    // optional serialport package at compile time.
    const spPkg = "serialport";
    const rlPkg = "@serialport/parser-readline";
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { SerialPort } = await (import(spPkg) as Promise<any>).catch(() => {
      throw new Error(
        "serialport package not installed. Run: npm install serialport --workspace apps/firefly-bridge"
      );
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { ReadlineParser } = await (import(rlPkg) as Promise<any>);

    const port = new (SerialPort as any)({
      path: this.devicePath,
      baudRate: 115200,
      autoOpen: false,
    });

    return new Promise((resolve, reject) => {
      port.open((err: Error | null) => {
        if (err) { reject(new Error(`Cannot open ${this.devicePath}: ${err.message}`)); return; }

        const parser = port.pipe(new (ReadlineParser as any)({ delimiter: "\n" }));
        const TIMEOUT_MS = 120_000; // 2 min — user has time to press the button
        const timer = setTimeout(() => {
          port.close();
          reject(new Error("Firefly approval timed out (120s)"));
        }, TIMEOUT_MS);

        // digestHex is computed on the device from the display fields (WYSIWYS).
        // We don't send it; the variable is unused on the host side.

        parser.on("data", (line: string) => {
          const trimmed = line.trim();
          // Skip non-JSON lines (boot messages, debug logs prefixed with [treasury]).
          if (!trimmed.startsWith("{")) return;
          clearTimeout(timer);
          port.close();
          try {
            const response = JSON.parse(trimmed) as { status: string; signature?: string };
            if (response.status === "ok" && response.signature) {
              resolve({ signature: response.signature, publicKey: this._publicKeyHex });
            } else {
              reject(new Error("Firefly approval rejected by operator"));
            }
          } catch {
            reject(new Error(`Unexpected response from device: ${trimmed}`));
          }
        });

        // Send all fields so the device can recompute the digest itself (WYSIWYS).
        // amount is a number so the device can format it identically (%.2f).
        // escrowCreateTxHash is the full hash, not truncated.
        const payload = JSON.stringify({
          cmd: "sign",
          display: {
            paymentId: req.paymentId,
            amount: req.amount,
            currency: req.currency,
            dest: req.dest,
            reference: req.reference,
            network: req.network,
            owner: req.owner,
            escrowSequence: req.escrowSequence,
            escrowCreateTxHash: req.escrowCreateTxHash,
          },
        });
        port.write(payload + "\n", (writeErr: Error | null) => {
          if (writeErr) { clearTimeout(timer); port.close(); reject(writeErr); }
        });
      });
    });
  }
}
