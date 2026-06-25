import { secp256k1 } from "@noble/curves/secp256k1";

// Generates a secp256k1 keypair for provisioning the Firefly Pixie device.
// Flash the private key onto the device and register the public key in the
// API's FIREFLY_PUBLIC_KEY environment variable.
const privateKey = secp256k1.utils.randomPrivateKey();
const publicKey = secp256k1.getPublicKey(privateKey, false).slice(1); // drop 0x04 prefix

console.log("FIREFLY_DEVICE_PRIVATE_KEY=" + Buffer.from(privateKey).toString("hex"));
console.log("FIREFLY_PUBLIC_KEY=" + Buffer.from(publicKey).toString("hex"));
