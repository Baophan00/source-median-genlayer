#!/usr/bin/env node
/**
 * Publish SourceMedian to GenLayer Studio Network.
 *
 *   node scripts/deploy_studionet.js
 *
 * A key pair is created next to this script on first use and reused after that,
 * so the creator address in the demo stays stable between runs.
 */
const fs = require("fs");
const path = require("path");
const { createClient, createAccount, generatePrivateKey } = require("genlayer-js");
const { studionet } = require("genlayer-js/chains");

const KEY_PATH = path.join(__dirname, ".source-median-keys.json");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function loadKeys() {
  if (fs.existsSync(KEY_PATH)) return JSON.parse(fs.readFileSync(KEY_PATH, "utf8"));
  const fresh = {
    creator: generatePrivateKey(),
    reader: generatePrivateKey(),
  };
  fs.writeFileSync(KEY_PATH, JSON.stringify(fresh, null, 2), { mode: 0o600 });
  return fresh;
}

const RPC_HICCUP = /DOCTYPE|fetch failed|ECONNRESET|timeout|temporarily unavailable|not available|rate limit/i;

async function retrying(label, fn) {
  let last;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      return await fn();
    } catch (error) {
      const message = String(error && error.message);
      if (!RPC_HICCUP.test(message)) {
        throw error;
      }
      last = error;
      const wait = /rate limit/i.test(message) ? 20000 : 4000;
      console.log(`  ${label}: rpc hiccup, retry ${attempt + 1} in ${wait / 1000}s`);
      await sleep(wait);
    }
  }
  throw last;
}

(async () => {
  const keys = loadKeys();
  const account = createAccount(keys.creator);
  const client = createClient({ chain: studionet, account });
  const source = new Uint8Array(fs.readFileSync(path.join(process.cwd(), "contracts/source_median.py")));

  console.log("creator", account.address);
  const hash = await retrying("deploy", () => client.deployContract({ code: source, args: [] }));
  console.log("deploy tx", hash);

  const receipt = await retrying("receipt", () =>
    client.waitForTransactionReceipt({ hash, status: "FINALIZED", retries: 200, interval: 3000 })
  );
  const address =
    receipt.data?.contract_address ||
    receipt.txDataDecoded?.contractAddress ||
    receipt.data?.contractAddress;
  if (!address) throw new Error(`no address in the receipt: ${JSON.stringify(receipt).slice(0, 600)}`);

  const stats = await retrying("stats", () => client.readContract({ address, functionName: "stats", args: [] }));
  console.log("contract", address);
  console.log("stats   ", JSON.stringify(stats));
  console.log(`\nnext: node scripts/e2e_studionet.js ${address}`);
})().catch((error) => {
  console.error("FAILED:", error.message);
  if (error.cause) console.error(String(error.cause).slice(0, 900));
  process.exit(1);
});
