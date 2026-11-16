#!/usr/bin/env node
/**
 * Three queries on GenLayer Studio Network, read from the published demo pages.
 *
 *   node scripts/e2e_studionet.js <contractAddress>
 *
 *   credits-1  three stations that agree (42, 42, 42)      -> median 42, reliable
 *   credits-2  two stations and an outlier (42, 42, 97)    -> median 42, unreliable
 *   credits-3  two stations and an offline one, min 3      -> refused, nothing stored
 *
 * Every URL below is a real public page; every number comes out of a real
 * consensus round on the live contract.
 */
const fs = require("fs");
const path = require("path");
const { createClient, createAccount, generatePrivateKey } = require("genlayer-js");
const { studionet } = require("genlayer-js/chains");

const ADDRESS = process.argv[2];
if (!ADDRESS) {
  console.error("usage: node scripts/e2e_studionet.js <contractAddress>");
  process.exit(1);
}

const KEY_PATH = process.env.SM_KEYS || path.join(__dirname, ".source-median-keys.json");
const keys = JSON.parse(fs.readFileSync(KEY_PATH, "utf8"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const BASE = process.env.SM_BASE || "https://sourcemedian-genlayer.surge.sh/demo";
const A = `${BASE}/station-a.html`;
const B = `${BASE}/station-b.html`;
const C = `${BASE}/station-c.html`;
const OUTLIER = `${BASE}/station-outlier.html`;
const OFFLINE = `${BASE}/station-broken.html`;

const QUESTION = "What daily credit count does the station report?";
const UNIT = "credits";
const MAX_VALUE = 1000000;

const parties = {
  creator: createClient({ chain: studionet, account: createAccount(keys.creator) }),
  reader: createClient({ chain: studionet, account: createAccount(keys.reader) }),
};
const watcher = createClient({ chain: studionet, account: createAccount(generatePrivateKey()) });

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

function executionFailed(receipt) {
  const leader = (receipt.consensus_data && receipt.consensus_data.leader_receipt) || [];
  return String(leader[0] && leader[0].execution_result).toUpperCase() === "ERROR";
}

async function call(role, fn, args) {
  console.log(`\n[${role}] ${fn}(${args.map((a) => JSON.stringify(a).slice(0, 64)).join(", ")})`);
  const hash = await retrying("send", () =>
    parties[role].writeContract({ address: ADDRESS, functionName: fn, args, value: 0n })
  );
  console.log(`  tx ${hash}`);
  const receipt = await retrying("receipt", () =>
    parties[role].waitForTransactionReceipt({ hash, status: "FINALIZED", retries: 240, interval: 3000 })
  );
  const failed = executionFailed(receipt);
  console.log(`  ${receipt.status_name || receipt.status}  (${failed ? "refused by the contract" : "executed"})`);
  return { hash, failed };
}

async function must(role, fn, args) {
  const out = await call(role, fn, args);
  if (out.failed) throw new Error(`${fn} was refused`);
  return out.hash;
}

async function register_once(role, args) {
  const id = args[0];
  try {
    await view("get_query", [id]);
    console.log(`  ${id} is already registered; reusing it`);
    return null;
  } catch (error) {
    if (RPC_HICCUP.test(String(error && error.message))) throw error;
    console.log(`  ${id} is not registered yet`);
  }
  try {
    return await must(role, "register", args);
  } catch (error) {
    try {
      await view("get_query", [id]);
      console.log(`  ${id} is already registered; reusing it`);
      return null;
    } catch (second) {
      throw error;
    }
  }
}

const view = (fn, args) =>
  retrying("read", () => watcher.readContract({ address: ADDRESS, functionName: fn, args }));

function describe(row) {
  if (!row) return "no reading";
  return `values ${JSON.stringify(row.values)} | median ${row.median} | spread ${String(row.spread).padStart(3)} | ${row.reliable ? "reliable" : "UNRELIABLE"} | sources ${row.source_count}`;
}

(async () => {
  console.log("contract", ADDRESS);
  console.log("pages   ", BASE);

  // ---------------------------------------------------------------- credits-1
  console.log("\n=== credits-1: three stations that agree ===");
  await register_once("creator", [
    "credits-1", QUESTION, UNIT, 10, MAX_VALUE, 3, JSON.stringify([A, B, C]),
  ]);
  let t0 = Date.now();
  await must("reader", "read", ["credits-1"]);
  console.log(`  round took ${Math.round((Date.now() - t0) / 1000)}s`);
  let row = await view("latest", ["credits-1"]);
  console.log(`  ${describe(row)}`);
  if (row.median !== 42 || row.reliable !== true) throw new Error("credits-1 did not read 42 as reliable");

  // ---------------------------------------------------------------- credits-2
  console.log("\n=== credits-2: two stations and an outlier ===");
  await register_once("creator", [
    "credits-2", QUESTION, UNIT, 10, MAX_VALUE, 2, JSON.stringify([A, B, OUTLIER]),
  ]);
  t0 = Date.now();
  await must("reader", "read", ["credits-2"]);
  console.log(`  round took ${Math.round((Date.now() - t0) / 1000)}s`);
  row = await view("latest", ["credits-2"]);
  console.log(`  ${describe(row)}`);
  if (row.median !== 42 || row.reliable !== false) throw new Error("credits-2 did not read 42 as unreliable");

  // ---------------------------------------------------------------- credits-3
  console.log("\n=== credits-3: two stations and an offline one, min_sources 3 ===");
  await register_once("creator", [
    "credits-3", QUESTION, UNIT, 10, MAX_VALUE, 3, JSON.stringify([A, B, OFFLINE]),
  ]);
  const refused = await call("reader", "read", ["credits-3"]);
  if (!refused.failed) throw new Error("credits-3 should have been refused: the offline station said nothing");
  const stored = await view("readings_of", ["credits-3"]);
  if (stored.length !== 0) throw new Error("a refused read stored a reading");
  console.log(`  nothing stored: ${stored.length} readings for credits-3`);

  // ---------------------------------------------------------------- evidence
  console.log("\n=== the queries as stored ===");
  for (const id of ["credits-1", "credits-2", "credits-3"]) {
    const query = await view("get_query", [id]);
    console.log(`  ${id} | ${query.question} | unit ${query.unit} | tolerance ${query.tolerance_pct}% | min ${query.min_sources} | round ${query.latest_round}`);
    for (const source of query.sources) console.log(`      ${source}`);
  }

  console.log("\nstats");
  console.log(JSON.stringify(await view("stats", []), null, 2));

  console.log(`\nexplorer https://explorer-studio.genlayer.com/address/${ADDRESS}`);
  console.log("\nRESULT: two settled reads (one reliable, one not), one refused read that stored nothing");
})().catch((error) => {
  console.error("\nFAILED:", error.message);
  if (error.cause) console.error(String(error.cause).slice(0, 900));
  process.exit(1);
});
