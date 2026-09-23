const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const babel = require("@babel/core");
const logic = require("../src/api/scanHistoryLogic");

test("history uses coin_name and scanned_at with creation time fallback", () => {
  const row = { id: "scan-id", coin_name: "Penny", scanned_at: "2026-01-02T00:00:00Z", created_at: "2026-01-03T00:00:00Z", estimated_value: null };
  assert.deepEqual(logic.normalizeScan(row), { id: "scan-id", coin: "Penny", time: row.scanned_at, value: null });
  assert.equal(logic.normalizeScan({ ...row, scanned_at: null }).time, row.created_at);
  assert.equal(logic.normalizeScan({}).coin, "Unidentified coin");
});

test("null, missing and invalid estimates display unavailable; zero remains a value", () => {
  for (const raw of [null, undefined, "", "invalid", Infinity]) {
    const { value } = logic.normalizeScan({ estimated_value: raw });
    assert.equal(value, null);
    assert.equal(logic.formatScanValue(value), "Value unavailable");
  }
  assert.equal(logic.normalizeScan({ estimated_value: "12.50" }).value, 12.5);
  assert.equal(logic.normalizeScan({ estimated_value: 0 }).value, 0);
  assert.equal(logic.formatScanValue(0), "~$0");
});

test("averages exclude unavailable estimates but include zero", () => {
  const scans = [null, 0, "12"].map(estimated_value => logic.normalizeScan({ coin_name: "Penny", estimated_value }));
  const [[, group]] = logic.groupScansByCoin(scans);
  assert.deepEqual(group, { count: 3, totalValue: 12, valuedCount: 2 });
  const [[, unavailable]] = logic.groupScansByCoin([logic.normalizeScan({ coin_name: "Penny", estimated_value: null })]);
  assert.equal(unavailable.valuedCount, 0);
});

const code = babel.transformFileSync("src/api/scans.js", {
  babelrc: false, configFile: false, plugins: ["@babel/plugin-transform-modules-commonjs"],
}).code;

function history({ token = "test-token", error = null, data = [], sessionError = false } = {}) {
  const calls = [];
  const builder = {
    select(columns) { calls.push(["select", columns]); return this; },
    order(column, options) { calls.push(["order", column, options.ascending, options.nullsFirst]); return this; },
    then(resolve, reject) { return Promise.resolve({ data, error }).then(resolve, reject); },
  };
  const supabase = {
    schema(name) { calls.push(["schema", name]); return this; },
    from(name) { calls.push(["from", name]); return builder; },
  };
  const context = { exports: {}, require: name => {
    if (name === "./client") return {};
    if (name === "./scanHistoryLogic") return logic;
    if (name === "./supabase") return { supabase, getAccessToken: async () => {
      if (sessionError) throw Error("expired");
      return token;
    }};
    throw Error("Unexpected import: " + name);
  }};
  vm.runInNewContext(code, context);
  return { fetchMyScans: context.exports.fetchMyScanHistory, calls };
}

test("own history SELECT relies on RLS and orders newest scan time first", async () => {
  const { fetchMyScans, calls } = history({ data: [{ id: "1", coin_name: "Penny", estimated_value: null }] });
  const result = await fetchMyScans();
  assert.equal(result[0].value, null);
  assert.deepEqual(calls, [
    ["schema", "public"], ["from", "scans"],
    ["select", "id,coin_name,country,denomination,year,estimated_value,scanned_at,created_at"],
    ["order", "scanned_at", false, false], ["order", "created_at", false, undefined],
  ]);
  // The stub intentionally exposes no write methods or user-id filter.
});

test("empty history returns an empty list", async () => {
  assert.equal((await history().fetchMyScans()).length, 0);
});

test("normal query failure reports a retryable message", async () => {
  await assert.rejects(history({ error: { message: "database unavailable" } }).fetchMyScans(), /try again/i);
});

test("missing and unreadable sessions prevent history queries", async () => {
  for (const options of [{ token: null }, { sessionError: true }]) {
    const { fetchMyScans, calls } = history(options);
    await assert.rejects(fetchMyScans(), /sign in/i);
    assert.equal(calls.length, 0);
  }
});
