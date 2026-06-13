import { writeFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { Client } from "xrpl";

const TESTNET_URL = "wss://s.altnet.rippletest.net:51233";
const ENV_PATH = resolve(process.cwd(), ".env");

async function main() {
  if (existsSync(ENV_PATH)) {
    console.error("Error: .env already exists. Delete it first if you want a new wallet.");
    process.exit(1);
  }

  const client = new Client(TESTNET_URL);

  try {
    console.log("Connecting to XRPL Testnet...");
    await client.connect();

    console.log("Requesting a new funded wallet from the faucet (may take 10–30s)...");
    const { wallet, balance } = await client.fundWallet();

    const envContents = [
      `XRPL_SEED="${wallet.seed}"`,
      `XRPL_ADDRESS="${wallet.address}"`,
      `XRPL_SERVER="${TESTNET_URL}"`,
      "",
    ].join("\n");

    writeFileSync(ENV_PATH, envContents, "utf8");

    console.log("\nWallet created and funded.");
    console.log(`Address : ${wallet.address}`);
    console.log(`Balance : ${balance} XRP`);
    console.log(`Seed    : saved to .env (not shown here)`);
    console.log(`\nView on explorer: https://testnet.xrpl.org/accounts/${wallet.address}`);
  } finally {
    await client.disconnect();
  }
}

main().catch((err) => {
  console.error("Failed to fund wallet:", err.message ?? err);
  process.exit(1);
});
