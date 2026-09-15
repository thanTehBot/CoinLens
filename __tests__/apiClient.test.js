const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const babel = require("@babel/core");

const code = babel.transformFileSync("src/api/client.js", {
  babelrc: false, configFile: false,
  plugins: ["@babel/plugin-transform-modules-commonjs"],
}).code;

function client({ token = "test-token", sessionError, status = 200, data = {}, networkError, invalidJson } = {}) {
  const calls = [];
  const context = {
    exports: {}, console,
    process: { env: { EXPO_PUBLIC_API_BASE_URL: "https://example.onrender.com/" } },
    require: name => {
      if (name === "expo-constants") return { expoConfig: {} };
      if (name === "./supabase") return { getAccessToken: async () => {
        if (sessionError) throw Error("session failed");
        return token;
      }};
      throw Error("Unexpected import " + name);
    },
    fetch: async (url, options) => {
      calls.push({ url, ...options });
      if (networkError) throw Error("offline");
      return { status, ok: status < 400, json: async () => {
        if (invalidJson) throw Error("not JSON");
        return data;
      }};
    },
  };
  vm.runInNewContext(code, context);
  return { api: context.exports, calls };
}

for (const source of ["camera", "gallery"]) {
  test(source + " scan sends JWT, images and timezone without supplied identity", async () => {
    const { api, calls } = client();
    await api.identifyCoin("front", source === "camera" ? "back" : null, { source, user_id: "untrusted" });
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "https://example.onrender.com/api/identify-coin");
    assert.equal(calls[0].headers.Authorization, "Bearer test-token");
    const body = JSON.parse(calls[0].body);
    assert.deepEqual(body, { front_image: "front", ...(source === "camera" ? { back_image: "back" } : {}), source, tz_offset_minutes: new Date().getTimezoneOffset() });
  });
}

test("actual camera and gallery handlers pass their sources", () => {
  const screen = fs.readFileSync("src/screens/scan/ScanScreen.js", "utf8");
  assert.match(screen, /identifyCoin\(frontImage, photo.base64, \{ source: "camera" \}\)/);
  assert.match(screen, /identifyCoin\(selectedUpload.base64, null, \{ source: "gallery" \}\)/);
});

for (const options of [{ token: null }, { sessionError: true }]) {
  test("missing or unreadable session prevents network access: " + JSON.stringify(options), async () => {
    const { api, calls } = client(options);
    await assert.rejects(api.identifyCoin("front", null, { source: "gallery" }), /sign in/i);
    assert.equal(calls.length, 0);
  });
}

test("unidentifiable 422 result preserves existing result handling", async () => {
  const data = { identification: { identifiable: false } };
  const { api } = client({ status: 422, data });
  assert.equal(await api.identifyCoin("front", null, { source: "gallery" }), data);
});

for (const [options, expected] of [
  [{ networkError: true }, "network"],
  [{ invalidJson: true }, "server_error"],
  [{ status: 401 }, "auth_invalid"],
  [{ status: 429, data: { error: { code: "rate_limit", message: "Wait" } } }, "rate_limit"],
]) {
  test("preserves error: " + expected, async () => {
    const { api } = client(options);
    await assert.rejects(api.authenticatedRequest("/api/example"), e => e.code === expected);
  });
}

test("listing uses the authenticated helper too", async () => {
  const { api, calls } = client();
  await api.generateEbayListing({ identification: { year: 1964 } });
  assert.equal(calls[0].headers.Authorization, "Bearer test-token");
  assert.match(calls[0].url, /generate-ebay-listing$/);
});
