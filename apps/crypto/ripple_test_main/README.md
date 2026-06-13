# Ripple_tests

Test XRPL Testnet payments from Node.js scripts.

## Setup

```bash
npm install
```

## 1. Create and fund a testnet wallet

```bash
npm run fund
```

This generates a new wallet, funds it from the Testnet faucet, and saves credentials to `.env`.

## 2. Send a test payment

```bash
npm run send -- <destination-address> <amount-xrp>
```

Example:

```bash
npm run send -- rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe 1
```

Use a second faucet-generated address as the destination for a first test.

## AI Tools

This project uses [XRPL AI Tools](https://share.google/6y64yufduCnXE4Xzm) for development. The **xrpl.org MCP server** (official XRPL documentation) is connected to Cursor, so the editor can look up current docs, API references, and SDK examples while you work on Testnet scripts.

## Notes

- `.env` contains your secret seed — never commit it.
- Testnet accounts and balances can be reset; run `npm run fund` again if needed.
- Explorer: https://testnet.xrpl.org
