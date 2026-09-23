// Pure error-display logic for the scan flow, kept free of React Native
// imports (unlike src/api/client.js, which pulls in Supabase/RN) so it can
// be unit tested directly under `node --test`.

class ScanError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.code = code;
    // OpenAI's real retry-after window, in seconds, for a rate_limit error
    // (server-provided; undefined when the server didn't include one).
    this.retryAfterSeconds = details.retryAfterSeconds;
  }
}

const ERROR_DISPLAY = {
  network: { icon: "!", title: "No Internet", tip: "Make sure WiFi or cellular data is enabled." },
  key_invalid: { icon: "!", title: "Invalid Server Key", tip: "Update the private key in the server environment." },
  key_missing: { icon: "!", title: "Server Key Missing", tip: "Add the private key to the server environment." },
  // tip is always overridden dynamically by describeRateLimit() below,
  // based on the server's real retry_after_seconds - kept here only for
  // icon/title consistency with every other entry in this table.
  rate_limit: { icon: "!", title: "Rate Limit Hit" },
  quota: { icon: "!", title: "Usage Limit Reached", tip: "Check the server provider billing." },
  server_error: { icon: "!", title: "Service Issue", tip: "Try again in a few minutes." },
  upstream_failure: { icon: "!", title: "Service Issue", tip: "Try again in a few minutes." },
  invalid_image: { icon: "!", title: "Unsupported Image", tip: "Try a clear JPEG or PNG photo." },
  missing_image: { icon: "!", title: "Photo Missing", tip: "Choose or capture a photo before scanning." },
  identification_failure: { icon: "!", title: "Coin Not Recognized", tip: "Try another photo with better lighting." },
  // Distinct from identification_failure: the AI ran out of its output
  // budget mid-processing (reasoning tokens consumed it all) before
  // producing any result - the image itself was never evaluated, so this
  // must not tell the user their photo/lighting was the problem.
  ai_incomplete: { icon: "!", title: "AI Processing Interrupted", tip: null },
  malformed_ai_response: { icon: "!", title: "Bad Identification Data", tip: "This is rare. Try scanning again." },
  camera: { icon: "!", title: "Camera Not Ready", tip: "Wait a moment, then try again." },
  photo: { icon: "!", title: "Photo Capture Failed", tip: "Make sure nothing is blocking the camera lens." },
  permission: { icon: "!", title: "Permission Needed", tip: "Enable photo or camera access and try again." },
  unidentifiable: { icon: "!", title: "Coin Not Recognized", tip: null },
  auth_required: { icon: "!", title: "Sign In Required", tip: "Sign in or create an account to identify and value coins." },
  auth_missing: { icon: "!", title: "Sign In Required", tip: "Sign in or create an account to identify and value coins." },
  auth_invalid: { icon: "!", title: "Session Expired", tip: "Sign out and sign back in, then try again." },
  quota_exceeded: { icon: "!", title: "Daily Scan Limit Reached", tip: "You've used today's scans. Try again tomorrow." },
  quota_check_failed: { icon: "!", title: "Service Issue", tip: "Couldn't verify your scan limit. Try again shortly." },
  image_too_large: { icon: "!", title: "Photo Too Large", tip: "Try a smaller or more compressed photo." },
  payload_too_large: { icon: "!", title: "Upload Too Large", tip: "Try a smaller or more compressed photo." },
  invalid_source: { icon: "!", title: "Something Went Wrong", tip: "Try scanning again." },
  scan_insert_failed: { icon: "!", title: "Couldn't Save Scan", tip: "The coin was identified but saving it failed. Try again." },
  unknown: { icon: "!", title: "Something Went Wrong", tip: "Try scanning again." },
};

// The one error code that should not offer a retry: the daily scan quota is
// exhausted, so retrying the same request will just fail again. The UI uses
// this to swap "Try Again" for "Back to Home" without touching any other
// error's retry flow.
function isRetryableErrorCode(code) {
  return code !== "quota_exceeded";
}

const SECONDS_PER_MINUTE = 60;
const SECONDS_PER_HOUR = 3600;

function pluralize(value, unit) {
  return `${value} ${unit}${value === 1 ? "" : "s"}`;
}

// Upstream OpenAI 429s can come with a retry-after ranging from a few
// seconds to multiple hours (the server-side quota reset window) - a
// short wait is worth sitting through with a retry, but a multi-minute or
// multi-hour one should send the user back to the app instead of stranding
// them on a dead-end screen. Never builds a countdown timer, just a
// one-time human-readable estimate.
function describeRateLimit(retryAfterSeconds) {
  if (typeof retryAfterSeconds !== "number" || !Number.isFinite(retryAfterSeconds) || retryAfterSeconds <= 0) {
    // The server didn't provide a usable retry-after - never claim a
    // specific wait time we don't actually have.
    return { tip: "Wait a short time and try again.", retryable: true };
  }

  if (retryAfterSeconds <= 60) {
    return {
      tip: `Try again in about ${pluralize(Math.round(retryAfterSeconds), "second")}.`,
      retryable: true,
    };
  }

  if (retryAfterSeconds < SECONDS_PER_HOUR) {
    const minutes = Math.max(1, Math.round(retryAfterSeconds / SECONDS_PER_MINUTE));
    return { tip: `Try again in about ${pluralize(minutes, "minute")}.`, retryable: false };
  }

  const hours = Math.max(1, Math.round(retryAfterSeconds / SECONDS_PER_HOUR));
  return { tip: `Try again in about ${pluralize(hours, "hour")}.`, retryable: false };
}

function makeErrorDetail(e) {
  const code = e instanceof ScanError ? e.code : "unknown";
  const display = ERROR_DISPLAY[code] ?? ERROR_DISPLAY.unknown;

  if (code === "rate_limit") {
    const { tip, retryable } = describeRateLimit(e.retryAfterSeconds);
    return { ...display, code, body: "The AI service is temporarily rate limited.", tip, retryable };
  }

  return { ...display, code, body: e.message, retryable: isRetryableErrorCode(code) };
}

module.exports = {
  ScanError,
  ERROR_DISPLAY,
  makeErrorDetail,
  isRetryableErrorCode,
  describeRateLimit,
};
