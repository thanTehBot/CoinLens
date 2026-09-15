import Constants from "expo-constants";

import { getAccessToken } from "./supabase";

function resolveApiBaseUrl() {
  const envUrl = process.env.EXPO_PUBLIC_API_BASE_URL?.trim();
  const configUrl = Constants.expoConfig?.extra?.apiBaseUrl?.trim();
  const url = envUrl || configUrl;

  if (url) return url.replace(/\/$/, "");

  console.warn("EXPO_PUBLIC_API_BASE_URL is not set - set it to your Render URL in .env.local");
  return "http://localhost:5000";
}

export const API_BASE_URL = resolveApiBaseUrl();
console.log("CoinLens API base URL:", API_BASE_URL);

export class ScanError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

const ERROR_DISPLAY = {
  network: { icon: "!", title: "No Internet", tip: "Make sure WiFi or cellular data is enabled." },
  key_invalid: { icon: "!", title: "Invalid Server Key", tip: "Update the private key in the server environment." },
  key_missing: { icon: "!", title: "Server Key Missing", tip: "Add the private key to the server environment." },
  rate_limit: { icon: "!", title: "Rate Limit Hit", tip: "Wait 30 seconds and try again." },
  quota: { icon: "!", title: "Usage Limit Reached", tip: "Check the server provider billing." },
  server_error: { icon: "!", title: "Service Issue", tip: "Try again in a few minutes." },
  upstream_failure: { icon: "!", title: "Service Issue", tip: "Try again in a few minutes." },
  invalid_image: { icon: "!", title: "Unsupported Image", tip: "Try a clear JPEG or PNG photo." },
  missing_image: { icon: "!", title: "Photo Missing", tip: "Choose or capture a photo before scanning." },
  identification_failure: { icon: "!", title: "Coin Not Recognized", tip: "Try another photo with better lighting." },
  malformed_ai_response: { icon: "!", title: "Bad Identification Data", tip: "This is rare. Try scanning again." },
  camera: { icon: "!", title: "Camera Not Ready", tip: "Wait a moment, then try again." },
  photo: { icon: "!", title: "Photo Capture Failed", tip: "Make sure nothing is blocking the camera lens." },
  permission: { icon: "!", title: "Permission Needed", tip: "Enable photo or camera access and try again." },
  unidentifiable: { icon: "!", title: "Coin Not Recognized", tip: null },
  auth_required: { icon: "!", title: "Sign In Required", tip: "Sign in or create an account to identify and value coins." },
  auth_missing: { icon: "!", title: "Sign In Required", tip: "Sign in or create an account to identify and value coins." },
  auth_invalid: { icon: "!", title: "Session Expired", tip: "Sign out and sign back in, then try again." },
  unknown: { icon: "!", title: "Something Went Wrong", tip: "Try scanning again." },
};

export function makeErrorDetail(e) {
  const code = e instanceof ScanError ? e.code : "unknown";
  const display = ERROR_DISPLAY[code] ?? ERROR_DISPLAY.unknown;
  return { ...display, body: e.message };
}

async function readJsonResponse(res) {
  try {
    return await res.json();
  } catch {
    throw new ScanError("server_error", `Server sent an unreadable response (HTTP ${res.status}).`);
  }
}

function throwForErrorResponse(res, data) {
  if (res.ok) return;

  const code = data?.error?.code || (res.status === 401 ? "auth_invalid" : res.status >= 500 ? "server_error" : "unknown");
  const message = data?.error?.message || `CoinLens request failed (HTTP ${res.status}).`;
  throw new ScanError(code, message);
}

export function toLegacyScanResult(result) {
  if (!result) return null;
  return {
    coinData: result.identification || null,
    numistaData: result.numista || null,
    pcgsData: result.pcgs || null,
    valueEstimate: result.valuation?.status === "available" ? result.valuation : null,
    summary: result.summary || null,
    coinLensResult: result,
  };
}

export async function authenticatedRequest(path, { method = "GET", body, acceptResponse } = {}) {
  let token;
  try {
    token = await getAccessToken();
  } catch {
    throw new ScanError("auth_invalid", "Unable to read your session. Please sign in again.");
  }
  if (!token) {
    throw new ScanError("auth_required", "Sign in to identify and value coins.");
  }

  let res;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  } catch {
    throw new ScanError("network", "No internet connection. Could not reach CoinLens.");
  }

  const data = await readJsonResponse(res);
  if (acceptResponse?.(res, data)) {
    return data;
  }
  throwForErrorResponse(res, data);
  return data;
}

export async function identifyCoin(frontImage, backImage = null, { source } = {}) {
  if (source !== "camera" && source !== "gallery") {
    throw new ScanError("photo", "Choose a camera or gallery photo before scanning.");
  }
  return authenticatedRequest("/api/identify-coin", {
    method: "POST",
    body: {
      front_image: frontImage,
      back_image: backImage || undefined,
      source,
      tz_offset_minutes: new Date().getTimezoneOffset(),
    },
    acceptResponse: (res, data) => res.status === 422 && data?.identification?.identifiable === false,
  });
}

export async function logScanToSheet(coinData, userName = "") {
  const coin = [coinData.year, coinData.country, coinData.denomination]
    .filter(v => v && v !== "Unknown")
    .join(" ");
  await fetch(`${API_BASE_URL}/api/log-scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ data: [{ Coin: coin, Time: new Date().toISOString(), User: userName }] }),
  }).catch(() => {});
}

export async function verifyAdminCode(code) {
  try {
    const res = await fetch(`${API_BASE_URL}/api/verify-admin-code`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
    const data = await res.json();
    return !!data.valid;
  } catch {
    return false;
  }
}

export async function generateEbayListing(coinLensResultOrCoinData, numistaData, valueEstimate, summary) {
  const payload = coinLensResultOrCoinData?.identification
    ? coinLensResultOrCoinData
    : {
        identification: coinLensResultOrCoinData,
        numista: numistaData,
        valuation: valueEstimate,
        summary,
      };

  return authenticatedRequest("/api/generate-ebay-listing", { method: "POST", body: payload });
}



