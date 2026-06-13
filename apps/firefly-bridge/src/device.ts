import { sha256 } from "@noble/hashes/sha256";
import { secp256k1 } from "@noble/curves/secp256k1";
import type { BridgeSignRequest } from "@treasury/shared";

// Signature/public-key byte formats are chosen to match the API's verifier
// (eth_keys in apps/api/app/tools/firefly.py):
//   - signature: 65 bytes, r(32) || s(32) || recovery(1), hex.
//   - publicKey: 64 bytes, uncompressed without the 0x04 prefix, hex.
export interface SignedApproval {
  signature: string;
  publicKey: string;
}

export interface FireflyDevice {
  /** Display the payment and sign once the button is pressed. */
  sign(req: BridgeSignRequest): Promise<SignedApproval>;
  publicKeyHex(): string;
}

/**
 * Canonical payload format — MUST stay identical to Python firefly.py:
 *   f"{payment_id}|{amount:.2f}|{currency}|{dest}"
 *
 * Any change here must be mirrored in apps/api/app/tools/firefly.py.
 */
export function deriveDigest(req: BridgeSignRequest): string {
  const canonical = `${req.paymentId}|${req.amount.toFixed(2)}|${req.currency}|${req.dest}`;
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
 * with a SerialFireflyDevice that talks to the github.com/firefly board over USB
 * and blocks on the physical button press.
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
