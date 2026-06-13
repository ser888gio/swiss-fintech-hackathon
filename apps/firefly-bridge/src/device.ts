import { secp256k1 } from "@noble/curves/secp256k1";

// Signature/public-key byte formats are chosen to match the API's verifier
// (eth_keys in apps/api/app/tools/firefly.py):
//   - signature: 65 bytes, r(32) || s(32) || recovery(1), hex.
//   - publicKey: 64 bytes, uncompressed without the 0x04 prefix, hex.
export interface SignedApproval {
  signature: string;
  publicKey: string;
}

export interface FireflyDevice {
  /** Show the request on the device and sign once the button is pressed. */
  sign(digestHex: string): Promise<SignedApproval>;
  publicKeyHex(): string;
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

  async sign(digestHex: string): Promise<SignedApproval> {
    const digest = Buffer.from(strip0x(digestHex), "hex");
    const sig = secp256k1.sign(digest, this.privateKey);
    const signature = Buffer.concat([
      sig.toCompactRawBytes(),
      Buffer.from([sig.recovery]),
    ]).toString("hex");
    return { signature, publicKey: this.publicKeyHex() };
  }
}
