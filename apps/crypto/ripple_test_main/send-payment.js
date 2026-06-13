import "dotenv/config";
import { Client, Wallet, xrpToDrops } from "xrpl";

function usage() {
  console.log(`Usage: npm run send -- <destination-address> <amount-xrp>

Example:
  npm run send -- rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe 1`);
}

async function main() {
  const destination = process.argv[2];
  const amountXrp = process.argv[3];

  if (!destination || !amountXrp) {
    usage();
    process.exit(1);
  }

  const { XRPL_SEED, XRPL_SERVER } = process.env;

  if (!XRPL_SEED || !XRPL_SERVER) {
    console.error("Error: XRPL_SEED and XRPL_SERVER must be set in .env");
    console.error("Run `npm run fund` first to create and fund a wallet.");
    process.exit(1);
  }

  const client = new Client(XRPL_SERVER);
  const wallet = Wallet.fromSeed(XRPL_SEED);

  try {
    console.log("Connecting to XRPL Testnet...");
    await client.connect();

    console.log(`Sending ${amountXrp} XRP from ${wallet.address}`);
    console.log(`Destination: ${destination}`);

    const result = await client.submitAndWait(
      {
        TransactionType: "Payment",
        Account: wallet.address,
        Amount: xrpToDrops(amountXrp),
        Destination: destination,
      },
      { wallet }
    );

    const txResult = result.result.meta.TransactionResult;
    const hash = result.result.hash;

    console.log(`\nResult: ${txResult}`);
    console.log(`Hash  : ${hash}`);
    console.log(`\nView on explorer: https://testnet.xrpl.org/transactions/${hash}`);

    if (txResult !== "tesSUCCESS") {
      process.exit(1);
    }
  } finally {
    await client.disconnect();
  }
}

main().catch((err) => {
  console.error("Payment failed:", err.message ?? err);
  process.exit(1);
});
