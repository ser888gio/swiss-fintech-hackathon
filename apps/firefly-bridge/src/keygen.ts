import { secp256k1 } from "@noble/curves/secp256k1";

// Generates a demo keypair for the mock Firefly device. Put the private key in
// the bridge's FIREFLY_MOCK_PRIVATE_KEY and the public key in the API's
// FIREFLY_PUBLIC_KEY so signatures verify end to end.
const privateKey = secp256k1.utils.randomPrivateKey();
const publicKey = secp256k1.getPublicKey(privateKey, false).slice(1); // drop 0x04 prefix

console.log("FIREFLY_MOCK_PRIVATE_KEY=" + Buffer.from(privateKey).toString("hex"));
console.log("FIREFLY_PUBLIC_KEY=" + Buffer.from(publicKey).toString("hex"));
