/**
 * AES-256-GCM encryption for the Firefly serial channel.
 *
 * When FIREFLY_SESSION_KEY is set (32-byte hex), all payloads sent to the
 * Firefly device over serial are encrypted. This protects against malware
 * running on the host that intercepts the serial port: without the session
 * key the interceptor sees only ciphertext and cannot forge a valid cmd.
 *
 * Key provisioning: both the bridge and the device firmware must share the
 * same 256-bit key. Provision at device setup time:
 *
 *   openssl rand -hex 32          # generate key
 *   # → write to .env as FIREFLY_SESSION_KEY=<hex>
 *   # → flash to device at provisioning (stored in device secure storage)
 *
 * The nonce (IV) is 12 random bytes per message (GCM standard). The auth tag
 * is 16 bytes and is verified by the receiver before decryption is trusted.
 * An anti-replay counter is embedded in the plaintext so a recorded encrypted
 * frame cannot be replayed for a different payment.
 */

import { createCipheriv, createDecipheriv, randomBytes } from "crypto";

const ALG = "aes-256-gcm";
const IV_BYTES = 12;

export interface EncryptedFrame {
  iv: string;   // 12-byte nonce, hex
  ct: string;   // ciphertext, hex
  tag: string;  // 16-byte GCM auth tag, hex
}

/**
 * Read the session key from the environment. Returns null when not configured
 * (plaintext fallback). Throws if the key is present but the wrong length.
 */
export function getSessionKey(): Buffer | null {
  const hex = process.env.FIREFLY_SESSION_KEY;
  if (!hex) return null;
  const key = Buffer.from(hex.replace(/^0x/, ""), "hex");
  if (key.length !== 32) {
    throw new Error(
      `FIREFLY_SESSION_KEY must be exactly 32 bytes (64 hex chars); got ${key.length} bytes`
    );
  }
  return key;
}

/**
 * Encrypt `plaintext` with AES-256-GCM using a fresh random nonce.
 * Returns an EncryptedFrame that can be JSON-serialised and sent over serial.
 */
export function encrypt(key: Buffer, plaintext: string): EncryptedFrame {
  const iv = randomBytes(IV_BYTES);
  const cipher = createCipheriv(ALG, key, iv);
  const ct = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();
  return {
    iv: iv.toString("hex"),
    ct: ct.toString("hex"),
    tag: tag.toString("hex"),
  };
}

/**
 * Decrypt an EncryptedFrame. Throws if the auth tag does not verify (tamper
 * protection) or if the IV / ciphertext is malformed.
 */
export function decrypt(key: Buffer, frame: EncryptedFrame): string {
  const decipher = createDecipheriv(ALG, key, Buffer.from(frame.iv, "hex"));
  decipher.setAuthTag(Buffer.from(frame.tag, "hex"));
  const pt = Buffer.concat([
    decipher.update(Buffer.from(frame.ct, "hex")),
    decipher.final(),
  ]);
  return pt.toString("utf8");
}
