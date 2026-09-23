import os
import re
import base64
import binascii
import json
import logging
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
from flask import Flask, Response, g, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from auth import require_auth
from require_user import require_user
from badges import evaluate_badges
from supabase_admin import (
    insert_scan,
    insert_api_usage,
    update_api_usage,
    count_api_usage_since,
    fetch_scans_for_user,
    fetch_scans_for_users,
    fetch_profile_created_at,
    fetch_leaderboard_rows,
    SupabaseAdminError,
)
from mock_openai import (
    MOCK_EBAY_LISTING,
    MOCK_MARKER,
    MOCK_NUMISTA,
    MOCK_PCGS,
    MOCK_SCAN_ROW,
    build_mock_coin_result as deterministic_mock_coin_result,
)

load_dotenv()

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
NUMISTA_API_KEY = os.environ.get("NUMISTA_API_KEY", "")
PCGS_BEARER_TOKEN = os.environ.get("PCGS_BEARER_TOKEN", "")
SHEETDB_URL = os.environ.get("SHEETDB_URL", "")
ADMIN_CODE = os.environ.get("ADMIN_CODE", "")
MOCK_MODE = os.environ.get("MOCK_MODE", "false").lower() == "true"
USE_MOCK_COIN_RESPONSE = os.environ.get("USE_MOCK_COIN_RESPONSE", "false").lower() == "true" or MOCK_MODE

# Configurable so the identification model can be changed (e.g. for cost or
# capability reasons) without a code change.
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# M6 cost protection: independent of any OpenAI-side spending limit.
DAILY_SCAN_LIMIT = int(os.environ.get("DAILY_SCAN_LIMIT", "20"))
MAX_IMAGE_BYTES = int(os.environ.get("MAX_IMAGE_BYTES", str(8 * 1024 * 1024)))

# V1: eBay listing generation is disabled by default (not part of the V1
# scope). The implementation is kept intact behind this flag so it can be
# re-enabled later without rebuilding it.
ENABLE_EBAY_LISTING = os.environ.get("ENABLE_EBAY_LISTING", "false").lower() == "true"

OPENAI_TIMEOUT = int(os.environ.get("OPENAI_TIMEOUT_SECONDS", "60"))
NUMISTA_TIMEOUT = int(os.environ.get("NUMISTA_TIMEOUT_SECONDS", "20"))
PCGS_TIMEOUT = int(os.environ.get("PCGS_TIMEOUT_SECONDS", "20"))

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
# Current OpenAI multimodal + structured-output endpoint. Used for the single
# identification call so the vision model returns schema-conformant JSON
# directly, instead of the old free-text-then-reparse approach.
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
NUMISTA_TYPES_URL = "https://api.numista.com/api/v3/types"
NUMISTA_COINS_URL = "https://api.numista.com/api/v3/coins"
NUMISTA_ISSUERS_URL = "https://api.numista.com/api/v3/issuers"
PCGS_PRICE_URL = "https://api.pcgs.com/publicapi/priceguide/getpricedata/{pcgs_number}"

REQUEST_TIMEOUT = 60

US_COUNTRY_NAMES = {"united states", "usa", "u.s.", "u.s.a.", "united states of america"}
MIN_IDENTIFICATION_CONFIDENCE = 40

app = Flask(__name__)
CORS(app)
# Two coin photos as base64 JSON comfortably fit well under this; guards
# against a client accidentally posting something enormous before we ever
# get to per-image validation.
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_CONTENT_LENGTH_BYTES", str(24 * 1024 * 1024)))

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
app.logger.handlers = logging.getLogger("gunicorn.error").handlers or app.logger.handlers
app.logger.setLevel(logging.getLogger("gunicorn.error").level or logging.INFO)


class CoinLensError(Exception):
    def __init__(self, code, message, status=500, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        # Optional extra fields merged into the error response body (e.g.
        # rate_limit's retry_after_seconds) - never used for anything
        # sensitive; see error_response().
        self.details = details or {}


def proxy_response(upstream_response):
    return Response(
        upstream_response.content,
        status=upstream_response.status_code,
        content_type=upstream_response.headers.get("Content-Type", "application/json"),
    )


def mock_coin_enabled():
    return MOCK_MODE or USE_MOCK_COIN_RESPONSE


def should_use_mock_coin_response():
    return mock_coin_enabled() or not OPENAI_API_KEY


def log_mock_response(route):
    app.logger.info("MOCK response: %s", route)


def error_response(error):
    body = {"code": error.code, "message": error.message}
    body.update(error.details)
    return jsonify({"error": body}), error.status


@app.errorhandler(CoinLensError)
def handle_coinlens_error(error):
    return error_response(error)


@app.errorhandler(413)
def handle_payload_too_large(_error):
    return error_response(CoinLensError("payload_too_large", "Upload is too large.", 413))


@app.errorhandler(HTTPException)
def handle_http_exception(error):
    # Flask/Werkzeug raise these for routing-level cases (unknown route -> 404,
    # wrong HTTP method -> 405, malformed request -> 400, etc). Without this
    # handler, the blanket Exception handler below catches them too and turns
    # every one - including a plain "wrong URL" - into a generic 500, which
    # reads as a server crash in logs when it's really just a 404/405. This
    # runs before the Exception handler because HTTPException is more specific
    # in the MRO (a still-more-specific code, like 413 above, wins over this).
    code = (error.name or "http_error").lower().replace(" ", "_")
    return error_response(CoinLensError(code, error.description or error.name or "Request failed.", error.code or 500))


@app.errorhandler(Exception)
def handle_unexpected_error(_error):
    return error_response(CoinLensError("server_error", "Unexpected server failure.", 500))


@app.route("/api/health", methods=["GET"])
def health():
    body = {
        "ok": True,
        "status": "ok",
        "mock_mode": should_use_mock_coin_response(),
        "has_openai_key": bool(OPENAI_API_KEY),
        "has_numista_key": bool(NUMISTA_API_KEY),
        "has_pcgs_token": bool(PCGS_BEARER_TOKEN),
        "has_sheetdb": bool(SHEETDB_URL),
    }
    if should_use_mock_coin_response():
        log_mock_response("/api/health")
    return jsonify(body)


@app.route("/api/me", methods=["GET"])
@require_user
def me():
    return jsonify({"id": g.user_id, "email": g.user_email})


# ---------------------------------------------------------------------------
# Authoritative badges (backend is now the single source of truth - see
# server/badges.py; src/badges/badges.js keeps only display metadata).
# Only the scan fields badge rules actually use are ever read/returned.
# ---------------------------------------------------------------------------

BADGE_SCAN_COLUMNS = "user_id,estimated_value,denom_canonical,is_foreign,local_date,local_hour,year,scanned_at"


@app.route("/api/badges/me", methods=["GET"])
@require_auth
def badges_me():
    """Identity comes only from the verified JWT (g.user_id via
    @require_auth) - a client can never request another user's badges."""
    try:
        scans = fetch_scans_for_user(g.user_id, BADGE_SCAN_COLUMNS)
        member_created_at = fetch_profile_created_at(g.user_id)
    except SupabaseAdminError as error:
        app.logger.error("badges_me fetch failed for user_id=%s: %s", g.user_id, error)
        return error_response(CoinLensError("badges_fetch_failed", "Could not load your badges right now.", 503))

    badge_count, earned_badge_ids = evaluate_badges(scans, member_created_at)
    return jsonify({"badge_count": badge_count, "earned_badge_ids": earned_badge_ids})


@app.route("/api/leaderboard", methods=["GET"])
@require_auth
def leaderboard_with_badges():
    """Authenticated (any signed-in user may see the public leaderboard),
    but every row's badge_count is computed server-side from that row's
    own scans - fetched here with the service-role client, in one batched
    query, and never returned to the client. Only the existing safe
    aggregate fields plus badge_count leave this function."""
    try:
        rows = fetch_leaderboard_rows()
    except SupabaseAdminError as error:
        app.logger.error("leaderboard fetch failed: %s", error)
        return error_response(CoinLensError("leaderboard_fetch_failed", "Could not load the leaderboard right now.", 503))

    user_ids = [row["user_id"] for row in rows if row.get("user_id")]
    try:
        scans = fetch_scans_for_users(user_ids, BADGE_SCAN_COLUMNS) if user_ids else []
    except SupabaseAdminError as error:
        app.logger.error("leaderboard badge-scan fetch failed: %s", error)
        return error_response(CoinLensError("leaderboard_fetch_failed", "Could not load the leaderboard right now.", 503))

    scans_by_user = {}
    for scan in scans:
        scans_by_user.setdefault(scan.get("user_id"), []).append(scan)

    result = []
    for row in rows:
        user_id = row.get("user_id")
        badge_count, _ = evaluate_badges(scans_by_user.get(user_id, []), row.get("member_since"))
        result.append({
            "user_id": user_id,
            "display_name": row.get("display_name"),
            "scan_count": row.get("scan_count"),
            "total_value": row.get("total_value"),
            "avg_value": row.get("avg_value"),
            "member_since": row.get("member_since"),
            "badge_count": badge_count,
        })

    app.logger.info(
        "[leaderboard] computed badge_count for %d user(s) from %d scan row(s)",
        len(rows), len(scans),
    )
    return jsonify(result)


def get_model_candidates(primary_model):
    if not primary_model:
        return [OPENAI_MODEL]
    if primary_model == OPENAI_MODEL:
        return [OPENAI_MODEL]
    return [primary_model, OPENAI_MODEL]


def is_retryable_openai_error(status, message):
    text = (message or "").lower()
    # Billing/spend-limit failures must never trigger a retry against another
    # model candidate - that just spends the same exhausted budget again.
    if status == 402 or "quota" in text or "billing" in text:
        return False
    return status in (400, 403, 404, 429) or "model" in text or "unsupported" in text or "not found" in text


def openai_chat_content(messages, max_tokens=400, model=None):
    if not OPENAI_API_KEY:
        raise CoinLensError("key_missing", "Server is missing OPENAI_API_KEY.", 500)

    candidates = get_model_candidates(model or OPENAI_MODEL)
    last_error = None
    for index, candidate_model in enumerate(candidates):
        payload = {"model": candidate_model, "messages": messages, "max_tokens": max_tokens}
        try:
            upstream = requests.post(
                OPENAI_CHAT_URL,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                },
                json=payload,
                timeout=OPENAI_TIMEOUT,
            )
        except requests.RequestException:
            last_error = CoinLensError("upstream_failure", "AI provider request failed.", 502)
            continue

        try:
            data = upstream.json()
        except ValueError:
            last_error = CoinLensError("upstream_failure", "AI provider returned an unreadable response.", 502)
            continue

        if not upstream.ok:
            message = data.get("error", {}).get("message", "")
            if upstream.status_code == 401:
                raise CoinLensError("key_invalid", "AI provider rejected the API key.", 401)
            if upstream.status_code == 402:
                raise CoinLensError("quota", "AI provider billing limit reached.", 402)
            if upstream.status_code == 429:
                code = "quota" if "quota" in message.lower() or "billing" in message.lower() else "rate_limit"
                if code == "quota":
                    raise CoinLensError(code, "AI provider rate or quota limit reached.", 429)
            if is_retryable_openai_error(upstream.status_code, message) and index < len(candidates) - 1:
                last_error = CoinLensError("upstream_failure", "AI provider rejected the requested model.", 502)
                continue
            if upstream.status_code == 429:
                raise CoinLensError("rate_limit", "AI provider rate limit reached.", 429)
            raise CoinLensError("upstream_failure", "AI provider request failed.", 502)

        content = data.get("choices", [{}])[0].get("message", {}).get("content")
        if content:
            return content.strip()

        last_error = CoinLensError("identification_failure", "AI provider returned an empty response.", 422)

    raise last_error or CoinLensError("upstream_failure", "AI provider did not return a usable response.", 502)


def find_matching_delimiter(text, open_index):
    opening = text[open_index]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escape_next = False

    for index in range(open_index, len(text)):
        char = text[index]
        if escape_next:
            escape_next = False
            continue
        if char == "\\":
            escape_next = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index
    return -1


def extract_json(text):
    if not isinstance(text, str) or not text.strip():
        raise CoinLensError("malformed_ai_response", "AI returned no recognizable data.", 502)

    trimmed = text.strip()
    starts = [index for index in (trimmed.find("{"), trimmed.find("[")) if index >= 0]
    if not starts:
        raise CoinLensError("malformed_ai_response", "AI returned no JSON data.", 502)

    start = min(starts)
    end = find_matching_delimiter(trimmed, start)
    if end < 0:
        raise CoinLensError("malformed_ai_response", "AI returned malformed JSON.", 502)

    try:
        return json.loads(trimmed[start:end + 1])
    except json.JSONDecodeError:
        raise CoinLensError("malformed_ai_response", "AI returned malformed JSON.", 502)


def guess_image_mime(image_bytes, supplied_mime=""):
    if supplied_mime in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
        return supplied_mime
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    if image_bytes.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    raise CoinLensError("invalid_image", "Unsupported or invalid image.", 415)


def check_image_size(image_bytes):
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise CoinLensError("image_too_large", "Image is too large. Use a smaller photo.", 413)


def decode_base64_image(value):
    if not value or not isinstance(value, str):
        raise CoinLensError("missing_image", "Front image is required.", 400)

    mime = ""
    raw = value
    if value.startswith("data:") and "," in value:
        header, raw = value.split(",", 1)
        mime = header[5:].split(";", 1)[0]

    try:
        image_bytes = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise CoinLensError("invalid_image", "Unsupported or invalid image.", 415)

    if not image_bytes:
        raise CoinLensError("invalid_image", "Unsupported or invalid image.", 415)

    check_image_size(image_bytes)
    mime = guess_image_mime(image_bytes, mime)
    return {"bytes": image_bytes, "mime": mime, "data_url": f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"}


def read_uploaded_image(file_storage, required=False):
    if not file_storage:
        if required:
            raise CoinLensError("missing_image", "Front image is required.", 400)
        return None
    image_bytes = file_storage.read()
    if not image_bytes:
        if required:
            raise CoinLensError("missing_image", "Front image is required.", 400)
        return None
    check_image_size(image_bytes)
    mime = guess_image_mime(image_bytes, file_storage.mimetype or "")
    return {"bytes": image_bytes, "mime": mime, "data_url": f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"}


def read_identification_images():
    if request.files:
        front = read_uploaded_image(request.files.get("front_image") or request.files.get("front"), required=True)
        back = read_uploaded_image(request.files.get("back_image") or request.files.get("back"), required=False)
        return front, back

    payload = request.get_json(force=True, silent=True) or {}
    front_value = payload.get("front_image") or payload.get("frontImage") or payload.get("front")
    back_value = payload.get("back_image") or payload.get("backImage") or payload.get("back")
    front = decode_base64_image(front_value)
    back = decode_base64_image(back_value) if back_value else None
    return front, back


def read_request_field(name):
    """Reads a plain (non-image) field from either a multipart or JSON body."""
    if request.files:
        return request.form.get(name)
    payload = request.get_json(force=True, silent=True) or {}
    return payload.get(name)


# ---------------------------------------------------------------------------
# Coin identification (single OpenAI call, structured output)
# ---------------------------------------------------------------------------

IDENTIFICATION_PROMPT = """You are an expert numismatist identifying a coin from one or two photos for a \
collector app. Examine the image(s) closely: obverse/front design, reverse/back design if shown, portraits, \
inscriptions and mottos, the date and mint mark exactly as visible, country and denomination text, metal color, \
surface wear and condition, and any doubling, off-center strikes, die cracks or other notable anomalies.

Set "status" to "identified" only when you are reasonably confident of the country, denomination, year, and mint \
mark (when the country/denomination normally carries one). Set it to "uncertain" whenever any of those fields is \
illegible, guessed, or unknown - even if the others are perfectly clear - or when the photo is blurry, too dark, \
cropped, glare-obscured, or otherwise not clear enough to be confident. When uncertain, explain in \
"unidentifiable_reason" what a better photo would need to show (for example: sharper focus, more even lighting, \
the full coin in frame, the reverse side, or a clearer view of the date). Never invent an identification you are \
not reasonably confident in.

"confidence" is a 0-100 self-assessment of how confident you are in the COMPLETE identification as a whole - \
country AND denomination AND year AND mint mark (when relevant) together - not just whichever parts happen to be \
clearly visible. This number is what downstream code uses to decide whether to search a coin catalog by country, \
denomination, and year, so a partial identification must score low even when some individual fields are obvious. \
For example: if the country and denomination are unmistakable but the year is worn away, cropped out, or \
otherwise not legible, confidence must be low (well under 40) and status must be "uncertain" - do not give a high \
confidence score just because part of the coin was easy to read. Only score confidence high (70 or above) when \
every field needed to look up this exact coin - country, denomination, year, and mint mark when relevant - is \
clearly legible with no guessing involved.

"estimated_grade" is your own visual estimate using the Sheldon scale (e.g. "VF-30") - make clear this is an \
estimate, not a professional certified grade.

Return ONLY the structured fields requested. Do not include any text outside the JSON object."""

IDENTIFICATION_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {
            "type": "string",
            "enum": ["identified", "uncertain"],
            "description": "identified only if country, denomination, year, and mint mark (when relevant) are all legible; uncertain if any of those is illegible, guessed, or unknown.",
        },
        "coin_name": {"type": "string"},
        "country": {"type": "string"},
        "denomination": {"type": "string"},
        "year": {"type": "string"},
        "mint_mark": {"type": ["string", "null"]},
        "estimated_grade": {"type": "string"},
        "confidence": {
            "type": "integer",
            "description": "0-100 confidence in the COMPLETE identification (country + denomination + year + mint mark together), not just the clearest individual field. Must be well under 40 if any of those fields is not legible.",
        },
        "description": {"type": "string"},
        "mint_errors": {"type": "array", "items": {"type": "string"}},
        "varieties": {"type": ["string", "null"]},
        "error_premium": {"type": "boolean"},
        "special_notes": {"type": "string"},
        "unidentifiable_reason": {"type": ["string", "null"]},
        "alternatives": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "coin": {"type": "string"},
                    "confidence": {"type": "integer"},
                },
                "required": ["coin", "confidence"],
            },
        },
    },
    "required": [
        "status", "coin_name", "country", "denomination", "year", "mint_mark",
        "estimated_grade", "confidence", "description", "mint_errors", "varieties",
        "error_premium", "special_notes", "unidentifiable_reason", "alternatives",
    ],
}


def normalize_identification(data):
    if not isinstance(data, dict):
        raise CoinLensError("malformed_ai_response", "AI identification was not an object.", 502)

    confidence = data.get("confidence", 0)
    try:
        confidence = max(0, min(100, int(confidence)))
    except (TypeError, ValueError):
        confidence = 0

    status = data.get("status")
    identifiable = status == "identified" and confidence >= MIN_IDENTIFICATION_CONFIDENCE

    if not identifiable:
        return {
            "coin_name": data.get("coin_name") or "Unidentified coin",
            "country": data.get("country") or "Unknown",
            "denomination": data.get("denomination") or "Unknown",
            "year": data.get("year") or "Unknown",
            "mint_mark": data.get("mint_mark"),
            "estimated_grade": data.get("estimated_grade") or "Unknown",
            "description": data.get("description") or data.get("special_notes") or "",
            "mint_errors": data.get("mint_errors") if isinstance(data.get("mint_errors"), list) else [],
            "varieties": data.get("varieties"),
            "error_premium": bool(data.get("error_premium")),
            "special_notes": data.get("special_notes") or "",
            "status": "uncertain",
            "identifiable": False,
            "unidentifiable_reason": data.get("unidentifiable_reason") or "The coin could not be identified confidently.",
            "confidence": confidence,
            "alternatives": data.get("alternatives") if isinstance(data.get("alternatives"), list) else [],
        }

    country = str(data.get("country") or "Unknown").strip() or "Unknown"
    denomination = str(data.get("denomination") or "Unknown").strip() or "Unknown"
    year = str(data.get("year") or "Unknown").strip() or "Unknown"
    coin_name = data.get("coin_name") or " ".join(part for part in [year, country, denomination] if part and part != "Unknown") or "Identified coin"

    return {
        "coin_name": coin_name,
        "country": country,
        "denomination": denomination,
        "year": year,
        "mint_mark": data.get("mint_mark"),
        "estimated_grade": data.get("estimated_grade") or "Unknown",
        "description": data.get("description") or data.get("special_notes") or "",
        "mint_errors": data.get("mint_errors") if isinstance(data.get("mint_errors"), list) else [],
        "varieties": data.get("varieties"),
        "error_premium": bool(data.get("error_premium")),
        "special_notes": data.get("special_notes") or "",
        "status": "identified",
        "identifiable": True,
        "confidence": confidence,
        "alternatives": data.get("alternatives") if isinstance(data.get("alternatives"), list) else [],
    }


def extract_responses_output_text(data):
    if isinstance(data, dict) and isinstance(data.get("output_text"), str) and data["output_text"].strip():
        return data["output_text"].strip()
    for item in (data.get("output") or []) if isinstance(data, dict) else []:
        for piece in item.get("content") or []:
            text = piece.get("text")
            if piece.get("type") in ("output_text", "text") and text:
                return text.strip()
    return None


# Diagnostics-only for a non-2xx OpenAI response (rate limits especially -
# these carry no `usage` field at all, so without this a 429 previously
# logged nothing but the generic CoinLensError). Never touches the request
# side (headers, payload, images) - only OpenAI's own response.
OPENAI_LOG_BODY_CHARS = 1500
OPENAI_RATE_LIMIT_HEADERS = (
    "x-request-id",
    "x-ratelimit-limit-requests",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-reset-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-tokens",
    "retry-after",
)
# Defense-in-depth beyond truncation: redacts any long base64-looking run
# before logging, in case an error body ever echoed request content back.
_BASE64_BLOB_RE = re.compile(r"[A-Za-z0-9+/]{100,}={0,2}")


def _sanitize_log_text(text, limit=OPENAI_LOG_BODY_CHARS):
    if not text:
        return text
    return _BASE64_BLOB_RE.sub("<redacted-base64>", text)[:limit]


def _log_openai_error_response(upstream):
    """Logs enough to diagnose a non-2xx OpenAI response - status, the
    standard rate-limit headers (only the ones actually present), and a
    sanitized/truncated body. Never logs the Authorization header, the API
    key, or any request payload."""
    present_headers = {
        name: upstream.headers[name] for name in OPENAI_RATE_LIMIT_HEADERS if name in upstream.headers
    }
    app.logger.warning(
        "[identify] OpenAI error response: http_status=%s headers=%s body=%s",
        upstream.status_code, present_headers, _sanitize_log_text(upstream.text),
    )


def _parse_retry_after_seconds(value):
    """Safely parses OpenAI's `retry-after` header (always sent as an
    integer number of seconds, not an HTTP-date) into a positive int.
    Returns None - never raises - for anything absent, non-numeric, or
    non-positive, so a malformed header can never fail the request."""
    if value is None:
        return None
    try:
        seconds = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def identify_coin_with_ai(front_image, back_image=None):
    if not OPENAI_API_KEY:
        raise CoinLensError("key_missing", "Server is missing OPENAI_API_KEY.", 500)

    content = [{"type": "input_text", "text": IDENTIFICATION_PROMPT}]
    content.append({"type": "input_image", "image_url": front_image["data_url"]})
    if back_image:
        content.append({"type": "input_image", "image_url": back_image["data_url"]})

    payload = {
        "model": OPENAI_MODEL,
        "input": [{"role": "user", "content": content}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "coin_identification",
                "schema": IDENTIFICATION_JSON_SCHEMA,
                "strict": True,
            }
        },
        # Reasoning-capable models spend part of this budget on hidden
        # reasoning tokens (counted in usage.output_tokens) before emitting
        # the final JSON - too low a cap can exhaust the whole budget on
        # reasoning and leave zero visible output text. 2000 leaves headroom
        # for that while still comfortably inside a low-tier TPM limit
        # alongside the (now-resized, ~4-5K token) input images.
        "max_output_tokens": 2000,
        # A real scan still hit output_tokens=reasoning_tokens=2000 with
        # status=incomplete/max_output_tokens - the model's default
        # reasoning effort consumed the entire budget with nothing left
        # for the visible JSON. Explicitly request low effort rather than
        # relying on whatever the default happens to be; max_output_tokens
        # is left at 2000 for now to isolate whether this alone fixes it.
        "reasoning": {"effort": "low"},
    }

    try:
        upstream = requests.post(
            OPENAI_RESPONSES_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {OPENAI_API_KEY}",
            },
            json=payload,
            timeout=OPENAI_TIMEOUT,
        )
    except requests.RequestException:
        raise CoinLensError("upstream_failure", "AI provider request failed.", 502)

    if not upstream.ok:
        _log_openai_error_response(upstream)

    try:
        data = upstream.json()
    except ValueError:
        raise CoinLensError("upstream_failure", "AI provider returned an unreadable response.", 502)

    # Logged regardless of success/failure (when present) so a 429 (real
    # per-request token cost) or an empty/truncated response (hit
    # max_output_tokens before emitting visible text - common with
    # reasoning-capable models spending the budget on hidden reasoning
    # tokens first) can both be diagnosed from Render logs instead of
    # guessing.
    usage = data.get("usage") if isinstance(data, dict) else None
    if isinstance(usage, dict):
        reasoning_tokens = (usage.get("output_tokens_details") or {}).get("reasoning_tokens") \
            if isinstance(usage.get("output_tokens_details"), dict) else None
        app.logger.info(
            "[identify] OpenAI usage: input_tokens=%s output_tokens=%s (reasoning=%s) "
            "total_tokens=%s response_status=%s http_status=%s",
            usage.get("input_tokens"), usage.get("output_tokens"), reasoning_tokens,
            usage.get("total_tokens"), data.get("status"), upstream.status_code,
        )

    if not upstream.ok:
        message = (data.get("error") or {}).get("message", "") if isinstance(data, dict) else ""
        if upstream.status_code == 401:
            raise CoinLensError("key_invalid", "AI provider rejected the API key.", 401)
        if upstream.status_code == 402:
            raise CoinLensError("quota", "AI provider billing limit reached.", 402)
        if upstream.status_code == 429:
            code = "quota" if "quota" in message.lower() or "billing" in message.lower() else "rate_limit"
            details = {}
            if code == "rate_limit":
                retry_after_seconds = _parse_retry_after_seconds(upstream.headers.get("retry-after"))
                if retry_after_seconds is not None:
                    details["retry_after_seconds"] = retry_after_seconds
            raise CoinLensError(code, "AI provider rate or quota limit reached.", 429, details=details)
        raise CoinLensError("upstream_failure", "AI provider request failed.", 502)

    # A real scan showed OpenAI return HTTP 200 with status="incomplete",
    # incomplete_details.reason="max_output_tokens" (the whole budget spent
    # on reasoning, none left for the visible JSON) - and no output_text.
    # That is a provider processing failure, not a genuine "coin not
    # recognized": must not be reported as identification_failure/
    # unidentifiable, which would tell the user to retake the photo when
    # the image itself was never the problem. Checked before the generic
    # empty-output-text fallback below, which remains for every other
    # empty-response cause.
    incomplete_details = data.get("incomplete_details") if isinstance(data, dict) else None
    if data.get("status") == "incomplete" and isinstance(incomplete_details, dict) \
            and incomplete_details.get("reason") == "max_output_tokens":
        app.logger.warning(
            "[identify] AI processing incomplete: incomplete_details=%s", incomplete_details,
        )
        raise CoinLensError(
            "ai_incomplete", "The AI service couldn't finish processing this scan.", 503,
        )

    text = extract_responses_output_text(data)
    if not text:
        app.logger.warning(
            "[identify] empty output_text: response_status=%s incomplete_details=%s",
            data.get("status") if isinstance(data, dict) else None,
            data.get("incomplete_details") if isinstance(data, dict) else None,
        )
        raise CoinLensError("identification_failure", "AI provider returned an empty response.", 422)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        raise CoinLensError("malformed_ai_response", "AI returned malformed JSON.", 502)

    return normalize_identification(parsed)


# ---------------------------------------------------------------------------
# Numista-first valuation
# ---------------------------------------------------------------------------

def _numista_result_list(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("types", "items", "results", "issues", "issuers"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _text_of(value):
    return str(value or "").strip().lower()


def _candidate_country_text(candidate):
    issuer = candidate.get("issuer")
    if isinstance(issuer, dict):
        return _text_of(issuer.get("name"))
    return _text_of(issuer or candidate.get("country"))


# ---------------------------------------------------------------------------
# Denomination normalization: a real UK 2012 20p scan showed the AI say
# "Twenty pence" while Numista titles say "20 Pence" - a plain substring
# check never matches, so "2 Pence"/"20 Pence"/"50 Pence" candidates all
# scored identically (country+year only), leaving the correct type
# ambiguous with an unrelated denomination. This is intentionally narrow -
# just enough number words and unit aliases for coin denominations, not a
# general NLP normalizer - and deliberately exact-match, not fuzzy: "2
# pence" must never canonicalize the same as "20 pence" or "50 pence".
# ---------------------------------------------------------------------------

_DENOMINATION_ONES = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
}
_DENOMINATION_TEENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_DENOMINATION_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_DENOMINATION_HUNDRED = {"hundred": 100}

# Currency-unit aliases: only collapsed where singular/plural (or the
# penny/pence irregular pair) is semantically unambiguous - never a blind
# "strip trailing s", since that would mangle "pence" itself.
NUMISTA_DENOMINATION_UNIT_ALIASES = {
    "penny": "pence", "pence": "pence",
    "cent": "cent", "cents": "cent",
    "dollar": "dollar", "dollars": "dollar",
    "pound": "pound", "pounds": "pound",
    "euro": "euro", "euros": "euro",
    "franc": "franc", "francs": "franc",
    "peso": "peso", "pesos": "peso",
    "rupee": "rupee", "rupees": "rupee",
    "shilling": "shilling", "shillings": "shilling",
    "krona": "krona", "kronor": "krona",
}


def _denomination_number_prefix(tokens):
    """Consumes a leading number word (including simple compounds like
    "twenty five") from `tokens`, returning (digit_string, remaining) or
    (None, tokens) if the first token isn't a recognized number word."""
    if not tokens:
        return None, tokens
    first = tokens[0]
    if first.isdigit():
        return first, tokens[1:]
    if first in _DENOMINATION_ONES:
        return str(_DENOMINATION_ONES[first]), tokens[1:]
    if first in _DENOMINATION_TEENS:
        return str(_DENOMINATION_TEENS[first]), tokens[1:]
    if first in _DENOMINATION_TENS:
        value = _DENOMINATION_TENS[first]
        rest = tokens[1:]
        if rest and rest[0] in _DENOMINATION_ONES:
            value += _DENOMINATION_ONES[rest[0]]
            rest = rest[1:]
        return str(value), rest
    if first in _DENOMINATION_HUNDRED:
        return str(_DENOMINATION_HUNDRED[first]), tokens[1:]
    return None, tokens


def normalize_numista_denomination(text):
    """Canonicalizes a denomination phrase to "<digits> <unit>" (e.g.
    "Twenty pence"/"twenty pence"/"20 Pence" -> "20 pence") so equal
    denominations compare equal regardless of AI wording vs. Numista's own
    title style - while "2 pence"/"20 pence"/"50 pence" always stay
    distinct, since a wrong digit is never normalized away."""
    if not text:
        return ""
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    if not tokens:
        return ""

    number, rest = _denomination_number_prefix(tokens)
    unit_tokens = [NUMISTA_DENOMINATION_UNIT_ALIASES.get(tok, tok) for tok in rest]
    if number is None:
        # No recognizable leading number - still useful as an exact-text
        # fallback (e.g. matching "Souvenir Token" against itself), just
        # never matches a real "<number> <unit>" denomination by accident.
        return " ".join([NUMISTA_DENOMINATION_UNIT_ALIASES.get(tok, tok) for tok in tokens])
    return " ".join([number] + unit_tokens)


def _numista_title_denomination(title):
    """Numista titles conventionally start "<denomination> - <series...>"
    (e.g. "20 Pence - Elizabeth II (...)") - takes the part before the
    first " - " as the candidate's own denomination phrase.

    Some titles have no " - " series separator at all and instead put a
    descriptive qualifier directly after the denomination in parentheses
    (e.g. "2 Dollars (Special Administration Region)") - a real Hong Kong
    $2 scan showed this trailing qualifier's words ("special",
    "administration", "region") getting folded into the normalized
    denomination by normalize_numista_denomination, which never matched
    the AI's plain "2 dollars" as a result. Stripping a trailing
    parenthetical here (only when it trails the whole title, i.e. there
    was no " - " to already remove it) fixes that without touching
    denomination equality itself - "20 Cents (Special Administration
    Region)" still normalizes to "20 cent", never "2 dollar"."""
    prefix = (title or "").split(" - ", 1)[0]
    prefix = re.sub(r"\s*\([^()]*\)\s*$", "", prefix).strip()
    return normalize_numista_denomination(prefix)


def _score_numista_candidate_breakdown(identification, candidate):
    """Same scoring as before, but returns (total, breakdown) so callers can
    log *why* a candidate gained or lost points instead of just a number -
    this is what actually lets a real search-response log line be diagnosed
    as a search problem vs. a scoring problem."""
    if not isinstance(candidate, dict):
        return 0, {}
    country = _text_of(identification.get("country"))
    denomination = _text_of(identification.get("denomination"))
    year = _text_of(identification.get("year"))
    title = _text_of(candidate.get("title"))
    cand_country = _candidate_country_text(candidate)

    breakdown = {}
    if country and country in cand_country:
        breakdown["country_issuer_match"] = 3
    if country and country in title:
        breakdown["country_in_title"] = 1
    canonical_denomination = normalize_numista_denomination(denomination)
    if canonical_denomination and canonical_denomination == _numista_title_denomination(candidate.get("title")):
        breakdown["denomination_in_title"] = 2
    if year and year in title:
        breakdown["year_in_title"] = 1
    min_year = candidate.get("min_year") or candidate.get("min_date")
    max_year = candidate.get("max_year") or candidate.get("max_date")
    try:
        if year.isdigit() and min_year is not None and max_year is not None:
            if int(min_year) <= int(year) <= int(max_year):
                breakdown["year_in_type_range"] = 2
    except (TypeError, ValueError):
        pass
    return sum(breakdown.values()), breakdown


def score_numista_candidate(identification, candidate):
    total, _ = _score_numista_candidate_breakdown(identification, candidate)
    return total


# Numista raw response bodies are logged truncated to this length - long
# enough to see the actual field shape (the thing we're verifying), short
# enough not to flood Render logs on every scan.
NUMISTA_LOG_BODY_CHARS = 1500

# ---------------------------------------------------------------------------
# Issuer resolution: a real scan (UK 20 pence, 2012) showed free-text search
# ("United Kingdom 20 pence") ranking same-denomination coins from unrelated
# issuers (mostly Isle of Man) ahead of the real match, and the issue-year
# check correctly rejected all of them - the search step itself wasn't
# giving the matching pipeline a fair shot. Numista's /types search accepts
# a structured `issuer` code (not an arbitrary country string), resolved
# here from Numista's own /issuers list - never a hardcoded/guessed code.
# ---------------------------------------------------------------------------

NUMISTA_ISSUER_CACHE_TTL_SECONDS = 24 * 60 * 60  # the issuer list barely changes; avoid refetching it every scan
_numista_issuer_cache = {"by_name": None, "fetched_at": 0.0}

# A handful of obvious AI-phrasing aliases for country names that don't
# literally match Numista's own issuer display name. Resolved before the
# real /issuers lookup, never as a substitute for it.
NUMISTA_ISSUER_NAME_ALIASES = {
    "uk": "united kingdom",
    "u.k.": "united kingdom",
    "usa": "united states",
    "u.s.a.": "united states",
    "us": "united states",
    "u.s.": "united states",
}


def fetch_numista_issuers():
    """Returns the raw list of Numista issuer records ({"code", "name", ...}),
    or None if the request itself failed."""
    try:
        upstream = requests.get(
            NUMISTA_ISSUERS_URL,
            headers={"Numista-API-Key": NUMISTA_API_KEY},
            timeout=NUMISTA_TIMEOUT,
        )
        upstream.raise_for_status()
        data = upstream.json()
    except (requests.RequestException, ValueError) as error:
        app.logger.warning("[numista] issuers fetch failed: error=%s", error)
        return None

    app.logger.info(
        "[numista] issuers response: status=%s body=%s",
        upstream.status_code, upstream.text[:NUMISTA_LOG_BODY_CHARS],
    )
    return _numista_result_list(data)


def _numista_issuer_name_index(force_refresh=False):
    """Returns {normalized_issuer_name: code}, refetched at most once per
    NUMISTA_ISSUER_CACHE_TTL_SECONDS (a simple in-process cache - no DB
    table, no extra service; fine for this prototype's single-process
    scale). Never raises: a fetch failure just serves whatever's already
    cached (possibly empty), which callers treat as "resolution failed,
    use the fallback search" rather than an error."""
    now = time.time()
    if not force_refresh and _numista_issuer_cache["by_name"] is not None \
            and (now - _numista_issuer_cache["fetched_at"]) < NUMISTA_ISSUER_CACHE_TTL_SECONDS:
        return _numista_issuer_cache["by_name"]

    issuers = fetch_numista_issuers()
    if issuers is None:
        return _numista_issuer_cache["by_name"] or {}

    by_name = {
        _text_of(issuer.get("name")): issuer.get("code")
        for issuer in issuers
        if isinstance(issuer, dict) and issuer.get("name") and issuer.get("code")
    }
    _numista_issuer_cache["by_name"] = by_name
    _numista_issuer_cache["fetched_at"] = now
    app.logger.info("[numista] issuer cache refreshed: %d issuer(s)", len(by_name))
    return by_name


def resolve_numista_issuer_code(country_text):
    """Maps an AI-identified country string to a real Numista issuer code
    via Numista's own (cached) /issuers list - never a hardcoded guess.
    Returns None - never raises - when the country is blank, the issuer
    list can't be fetched, or nothing matches; callers must fall back to a
    non-issuer-scoped search rather than failing the whole scan."""
    normalized = _text_of(country_text)
    if not normalized:
        return None
    normalized = NUMISTA_ISSUER_NAME_ALIASES.get(normalized, normalized)
    try:
        by_name = _numista_issuer_name_index()
    except Exception as error:  # belt-and-suspenders: must never fail a scan
        app.logger.warning("[numista] issuer resolution failed unexpectedly: %s", error)
        return None
    return by_name.get(normalized)


def _numista_year_param(identification):
    year_text = _text_of(identification.get("year"))
    return int(year_text) if year_text.isdigit() else None


def _numista_search_request(params, label):
    """Runs one /types search with the given params, logging under `label`
    (e.g. "structured"/"fallback"). Returns a list (possibly empty) of
    candidates, or None if the request itself failed."""
    try:
        upstream = requests.get(
            NUMISTA_TYPES_URL,
            params=params,
            headers={"Numista-API-Key": NUMISTA_API_KEY},
            timeout=NUMISTA_TIMEOUT,
        )
    except requests.RequestException as error:
        app.logger.error("[numista] %s search request failed: params=%s error=%s", label, params, error)
        return None

    app.logger.info(
        "[numista] %s search response: params=%s status=%s body=%s",
        label, params, upstream.status_code, upstream.text[:NUMISTA_LOG_BODY_CHARS],
    )
    try:
        upstream.raise_for_status()
        results = _numista_result_list(upstream.json())
    except (requests.RequestException, ValueError) as error:
        app.logger.error("[numista] %s search response unusable: params=%s error=%s", label, params, error)
        return None

    app.logger.info("[numista] candidate count=%d (%s search)", len(results), label)
    return results


def search_numista_types(identification):
    """Returns a list of candidate Numista types, or None if the lookup
    itself failed (as opposed to succeeding with zero results).

    Prefers a structured search scoped to the AI-identified country's real
    Numista issuer code (see resolve_numista_issuer_code) plus denomination
    and year, instead of stuffing the country name into free-text `q` -
    real scans showed free text ranking same-denomination coins from
    unrelated issuers ahead of the correct one. Falls back to a
    denomination(+year)-only search, still feeding the existing
    scoring/issue-validation pipeline, when issuer resolution fails or the
    structured search itself returns nothing usable - never falls back to
    blindly picking a free-text result."""
    denomination = (identification.get("denomination") or "").strip()
    if not denomination:
        app.logger.info("[numista] search skipped: no denomination to build a query from")
        return []

    country = (identification.get("country") or "").strip()
    year = _numista_year_param(identification)
    issuer_code = resolve_numista_issuer_code(country) if country else None
    app.logger.info("[numista] issuer resolution: AI country=%r resolved issuer code=%r", country, issuer_code)

    if issuer_code:
        structured_params = {"q": denomination, "issuer": issuer_code, "category": "coin", "count": 12}
        if year is not None:
            structured_params["year"] = year
        app.logger.info("[numista] search params: %s", structured_params)
        results = _numista_search_request(structured_params, "structured")
        if results:
            return results
        app.logger.info(
            "[numista] falling back to denomination-only search: structured search %s",
            "failed" if results is None else "returned no candidates",
        )
    else:
        app.logger.info("[numista] falling back to denomination-only search: issuer resolution failed")

    fallback_params = {"q": denomination, "category": "coin", "count": 12}
    if year is not None:
        fallback_params["year"] = year
    app.logger.info("[numista] search params (fallback): %s", fallback_params)
    return _numista_search_request(fallback_params, "fallback")


def fetch_numista_type_detail(type_id):
    try:
        upstream = requests.get(
            f"{NUMISTA_TYPES_URL}/{type_id}",
            headers={"Numista-API-Key": NUMISTA_API_KEY},
            timeout=NUMISTA_TIMEOUT,
        )
        upstream.raise_for_status()
        data = upstream.json()
    except (requests.RequestException, ValueError) as error:
        app.logger.warning("[numista] type detail fetch failed: type_id=%s error=%s", type_id, error)
        return None

    app.logger.info(
        "[numista] type detail response: type_id=%s status=%s body=%s",
        type_id, upstream.status_code, upstream.text[:NUMISTA_LOG_BODY_CHARS],
    )
    return data if isinstance(data, dict) else None


# Numista v3 separates a *type* (e.g. "1 Dollar - Elizabeth II") from its
# *issues* (the specific year/mint-mark variants struck under that type).
# A type's own min_year/max_year is only the overall production range, and
# pricing is per-issue, not per-type - so a title/country score, however
# good, is not enough to call a match "confident": we require a real issue
# record for the identified year before selecting a type at all.
NUMISTA_MATCH_CANDIDATES_TO_INSPECT = 3  # how many top-scored types get an /issues lookup - keeps API usage bounded
NUMISTA_MATCH_MIN_SCORE = 2  # below this, a candidate isn't worth spending an extra HTTP call on at all


def fetch_numista_issues(type_id):
    """Returns a type's issue records (its specific year/mint-mark variants),
    or None if the request itself failed."""
    try:
        upstream = requests.get(
            f"{NUMISTA_TYPES_URL}/{type_id}/issues",
            headers={"Numista-API-Key": NUMISTA_API_KEY},
            timeout=NUMISTA_TIMEOUT,
        )
        upstream.raise_for_status()
        data = upstream.json()
    except (requests.RequestException, ValueError) as error:
        app.logger.warning("[numista] issues fetch failed: type_id=%s error=%s", type_id, error)
        return None

    app.logger.info(
        "[numista] issues response: type_id=%s status=%s body=%s",
        type_id, upstream.status_code, upstream.text[:NUMISTA_LOG_BODY_CHARS],
    )
    issues = _numista_result_list(data)
    app.logger.info(
        "[numista] issues inspected: type_id=%s count=%d years=%s",
        type_id, len(issues),
        [issue.get("year", (issue.get("min_year"), issue.get("max_year"))) for issue in issues if isinstance(issue, dict)],
    )
    return issues


def _issue_matches_year(issue, year_text):
    if not isinstance(issue, dict) or not year_text.isdigit():
        return False
    target = int(year_text)
    try:
        issue_year = issue.get("year")
        if issue_year is not None and int(issue_year) == target:
            return True
    except (TypeError, ValueError):
        pass
    try:
        min_year, max_year = issue.get("min_year"), issue.get("max_year")
        if min_year is not None and max_year is not None and int(min_year) <= target <= int(max_year):
            return True
    except (TypeError, ValueError):
        pass
    return False


def _issue_mint_text(issue):
    if not isinstance(issue, dict):
        return ""
    mint = issue.get("mint")
    if isinstance(mint, dict):
        return _text_of(mint.get("name") or mint.get("code"))
    mints = issue.get("mints")
    if isinstance(mints, list):
        return " ".join(_text_of(m.get("name") or m.get("code")) for m in mints if isinstance(m, dict))
    return _text_of(issue.get("mint_letter") or issue.get("mintmark"))


# A real UK 2012 20 pence type had three issues for that year alone: an
# ordinary circulation strike, a "BU" (brilliant uncirculated), and a
# "Proof". Same intent as the type-level looks_special_or_proof/
# ai_indicates_special_variant pair above - just applied one level down,
# to an issue's own comment/finish field instead of a type's object_type.
#
# NOTE: "uncirculated"/"brilliant" were missing from the original keyword
# set - a real 2016 Canada 5-cent scan showed a "853959 comment=
# 'Uncirculated'" issue misclassified as ordinary (special=False) as a
# result, causing it to tie with the genuinely ordinary issue and reject
# the whole type as ambiguous. This is a Numista *issue-comment* concept
# (a specific mint/collector product), unrelated to an "AU" (About
# Uncirculated) *condition grade* the AI assigns to the physical coin -
# the two must never be conflated (see ai_indicates_special_variant, which
# only ever looks at the AI's own identification text, never an issue's
# Numista comment).
ISSUE_SPECIAL_KEYWORDS = {
    "proof", "prooflike", "specimen", "bu", "uncirculated", "brilliant", "pattern", "matte",
}
# Phrases built from otherwise-generic words ("edition", "set") that are
# only trustworthy as a special-issue signal together, checked against the
# whole comment text rather than as individual tokens.
ISSUE_SPECIAL_PHRASES = ("special edition", "mint set", "proof set")


def _issue_special_text(issue):
    if not isinstance(issue, dict):
        return ""
    return " ".join(
        _text_of(issue.get(field))
        for field in ("comment", "comments", "finish", "description")
        if issue.get(field)
    )


def _looks_special_issue(issue):
    """True when an issue's own comment/finish text flags it as a
    proof/BU/specimen/uncirculated/special-edition strike rather than an
    ordinary one. Single keywords match whole words (not substrings), so
    a short one like "bu" can't false-positive inside an unrelated word;
    multi-word phrases built from generic words ("special edition") are
    matched as phrases instead, for the same reason."""
    text = _issue_special_text(issue)
    if any(phrase in text for phrase in ISSUE_SPECIAL_PHRASES):
        return True
    words = set(re.findall(r"[a-z]+", text))
    return bool(words & ISSUE_SPECIAL_KEYWORDS)


def _select_issue_for_year(identification, issues, type_id=None):
    """Among a type's issues, finds one matching the identified year. Mint
    mark (when the AI reported one) disambiguates first, never as a hard
    requirement. If several same-year issues remain and the AI didn't
    itself flag a proof/BU/special strike, prefers whichever aren't
    flagged special in their own comment/finish text - but only when
    exactly one ordinary issue remains; if issues are still tied (multiple
    ordinary ones, or the AI *did* flag something special and more than
    one candidate remains), returns (None, reason) rather than guessing,
    exactly like the type-level ambiguity guard.

    Returns (selected_issue_or_None, reason). `reason` is None on success,
    or a short string naming the actual predicate that failed - a caller
    logging a single generic "no issue matches year" for every failure
    mode (year, mint, or variant ambiguity) was shown by a real scan to be
    actively misleading when the year *did* match. `type_id` is optional,
    used only to tag the per-issue diagnostic log lines below.

    Diagnostic logging (kept, not just temporary - concise and has proven
    useful for diagnosing a live mismatch unit tests didn't catch): logs
    one line per year-matching issue with every predicate this function
    actually evaluates, plus whether that issue was the one accepted."""
    year_text = _text_of(identification.get("year"))
    year_matches = [issue for issue in (issues or []) if _issue_matches_year(issue, year_text)]
    if not year_matches:
        return None, "no issue matches year"

    mint_mark = _text_of(identification.get("mint_mark"))
    ai_special = ai_indicates_special_variant(identification)

    candidates = year_matches
    selected = None
    reason = None

    if len(candidates) > 1 and mint_mark:
        mint_matches = [issue for issue in candidates if mint_mark in _issue_mint_text(issue)]
        if len(mint_matches) == 1:
            selected = mint_matches[0]
        elif mint_matches:
            candidates = mint_matches

    if selected is None:
        if len(candidates) == 1:
            selected = candidates[0]
        elif ai_special:
            # The AI itself flagged proof/BU/special - never force-pick
            # "the ordinary one" on its behalf; still ambiguous.
            reason = "year matched but AI indicated a special issue and multiple candidates remain ambiguous"
        else:
            ordinary_matches = [issue for issue in candidates if not _looks_special_issue(issue)]
            if len(ordinary_matches) == 1:
                selected = ordinary_matches[0]
            elif len(ordinary_matches) > 1:
                reason = "year matched but multiple ordinary issues remain indistinguishable"
            else:
                reason = "year matched but no compatible ordinary/mint variant remained"

    for issue in year_matches:
        is_selected = selected is not None and issue.get("id") == selected.get("id")
        app.logger.info(
            "[numista] issue evaluation: type_id=%s issue_id=%s year_match=true mint_match=%s special=%s "
            "comment=%r decision=%s",
            type_id, issue.get("id"),
            bool(mint_mark) and mint_mark in _issue_mint_text(issue),
            _looks_special_issue(issue),
            _issue_special_text(issue),
            "accepted" if is_selected else f"rejected ({reason or 'not the selected issue'})",
        )

    return selected, reason


# ---------------------------------------------------------------------------
# Variant disambiguation: a real UK 2012 20p scan found THREE candidates all
# with a valid 2012 issue - a standard circulation type, a non-circulating
# 1/10oz fine-silver type, and a silver-proof variant of the standard type.
# The year/issue gate correctly refused to guess between them. For an
# ordinary circulating coin (the AI didn't say proof/silver/gold/etc.),
# Numista's own object_type + title already distinguish "the everyday coin"
# from a collector variant - no extra API calls needed.
# ---------------------------------------------------------------------------

NUMISTA_STANDARD_CIRCULATION_OBJECT_TYPE = "standard circulation coins"

# Checked against a *candidate's* object_type/title - deliberately narrower
# than the AI-side keyword list below (no bare "silver"/"gold": plenty of
# genuinely standard circulating coins are historically silver or gold, so
# only the more specific collector/bullion phrasing counts here).
NUMISTA_CANDIDATE_SPECIAL_KEYWORDS = ("proof", "fine silver", "fine gold", "bullion", "specimen", "commemorative", "platinum")

# Checked against the AI's own identification text - a live AI describing an
# ordinary coin it's looking at essentially never says "silver"/"gold"
# unless the coin actually is one, so the fuller word list is safe here.
AI_SPECIAL_VARIANT_KEYWORDS = ("proof", "silver", "gold", "platinum", "bullion", "specimen", "commemorative")


def looks_special_or_proof(candidate):
    """True when a Numista candidate is a proof/precious-metal/
    non-circulating/commemorative variant rather than an ordinary
    circulation strike - based only on object_type/title fields Numista's
    search already returns, no extra API calls."""
    if not isinstance(candidate, dict):
        return False
    object_type = candidate.get("object_type")
    object_type_name = _text_of(object_type.get("name")) if isinstance(object_type, dict) else ""
    if object_type_name and object_type_name != NUMISTA_STANDARD_CIRCULATION_OBJECT_TYPE:
        return True
    title = _text_of(candidate.get("title"))
    return any(keyword in title for keyword in NUMISTA_CANDIDATE_SPECIAL_KEYWORDS)


def ai_indicates_special_variant(identification):
    """True when the AI's own identification explicitly points at a
    proof/precious-metal/commemorative strike, in which case we must not
    assume "ordinary circulation coin" on its behalf."""
    text = " ".join(
        _text_of(identification.get(field))
        for field in ("description", "special_notes", "coin_name", "varieties", "estimated_grade")
    )
    return any(keyword in text for keyword in AI_SPECIAL_VARIANT_KEYWORDS)


def resolve_numista_type_and_issue(identification, candidates):
    """Scores every candidate type (logging the full breakdown for each -
    not just the winner - so a real search response can be diagnosed as a
    search problem vs. a scoring problem), then inspects the top few
    candidates' real issue records and requires one to actually match the
    identified year. A well-scored title is only a hint about which
    candidates are worth an /issues lookup - it is never enough on its own
    to select a match. Returns (type_candidate, issue) or (None, None)."""
    if not candidates:
        return None, None

    scored = sorted(
        (( *_score_numista_candidate_breakdown(identification, c), c) for c in candidates),
        key=lambda entry: entry[0], reverse=True,
    )
    app.logger.info(
        "[numista] all candidates scored: %s",
        [
            (total, candidate.get("id"), candidate.get("title"), _candidate_country_text(candidate), breakdown)
            for total, breakdown, candidate in scored
        ],
    )

    to_inspect = [entry for entry in scored if entry[0] >= NUMISTA_MATCH_MIN_SCORE][:NUMISTA_MATCH_CANDIDATES_TO_INSPECT]
    if not to_inspect:
        app.logger.info(
            "[numista] no confident match: no candidate reached the minimum score of %s to justify an issues lookup",
            NUMISTA_MATCH_MIN_SCORE,
        )
        return None, None

    # Checks every inspected candidate (not just the first hit) so that
    # multiple types with a real matching issue can be detected as
    # ambiguous, rather than silently trusting whichever scored highest -
    # the score already proved unreliable for ranking (see the module
    # comment above search_numista_types); it must not also be trusted for
    # tie-breaking a factual match.
    matches = []
    for total, _breakdown, candidate in to_inspect:
        type_id = candidate.get("id")
        if type_id is None:
            continue
        issues = fetch_numista_issues(type_id)
        if issues is None:
            app.logger.warning("[numista] skipping candidate id=%s: issues lookup failed", type_id)
            continue
        selected_issue, rejection_reason = _select_issue_for_year(identification, issues, type_id=type_id)
        if selected_issue is None:
            # rejection_reason distinguishes "no issue matches year" from
            # "year matched but mint/variant filtering left it ambiguous" -
            # a real scan showed the old single generic message here was
            # misleading once year matches existed but were filtered out
            # for an unrelated reason.
            app.logger.info(
                "[numista] rejected candidate id=%s title=%r score=%s: %s",
                type_id, candidate.get("title"), total, rejection_reason or "no compatible issue found",
            )
            continue
        matches.append((candidate, selected_issue))

    if not matches:
        app.logger.info(
            "[numista] no confident match: none of the top %d inspected candidate(s) had a matching issue",
            len(to_inspect),
        )
        return None, None

    # Denomination disambiguation: a real UK 2012 20p scan showed "2
    # Pence"/"20 Pence"/"50 Pence" all tie on country+year alone once the
    # AI's wording ("Twenty pence") didn't literally appear in any title -
    # canonical denomination equality (exact, never fuzzy - "20 pence"
    # must never match "2 pence") narrows to whichever tied matches are
    # actually the identified denomination, before variant resolution.
    if len(matches) > 1:
        ai_denomination = normalize_numista_denomination(identification.get("denomination"))
        if ai_denomination:
            denomination_matches = [
                (c, i) for c, i in matches if _numista_title_denomination(c.get("title")) == ai_denomination
            ]
            if denomination_matches:
                app.logger.info(
                    "[numista] denomination disambiguation: narrowing to %d candidate(s) matching denomination=%r, "
                    "dropping: %s",
                    len(denomination_matches), ai_denomination,
                    [(c.get("id"), c.get("title")) for c, i in matches
                     if _numista_title_denomination(c.get("title")) != ai_denomination],
                )
                matches = denomination_matches

    # Variant disambiguation: only when there's still a tie AND the AI
    # didn't itself flag a proof/precious-metal/commemorative coin. Never
    # applied to break a tie the AI's own words argue against, and never
    # applied to reject the year/issue check's own result - if it leaves
    # zero or one standard-circulation candidate, that's the new decision;
    # if it can't narrow anything (no standard match at all), the original
    # matches are left untouched for the ambiguity check below.
    if len(matches) > 1 and not ai_indicates_special_variant(identification):
        standard_matches = [(c, i) for c, i in matches if not looks_special_or_proof(c)]
        if standard_matches:
            app.logger.info(
                "[numista] variant disambiguation: preferring %d standard-circulation candidate(s), "
                "deprioritizing special-variant match(es): %s",
                len(standard_matches),
                [(c.get("id"), c.get("title")) for c, i in matches if looks_special_or_proof(c)],
            )
            matches = standard_matches

    if len(matches) > 1:
        app.logger.info(
            "[numista] no confident match: %d candidates all had an issue matching year=%r - ambiguous, not guessing: %s",
            len(matches), identification.get("year"),
            [(c.get("id"), c.get("title"), issue.get("id")) for c, issue in matches],
        )
        return None, None

    candidate, selected_issue = matches[0]
    app.logger.info(
        "[numista] selected type+issue: type_id=%s title=%r issue_id=%s issue_year=%s",
        candidate.get("id"), candidate.get("title"), selected_issue.get("id"), selected_issue.get("year"),
    )
    return candidate, selected_issue


def lookup_numista(identification):
    """Finds the strongest practical Numista type+issue match for the
    identified coin. Returns None when no confident match exists - callers
    must not treat that as an error, only as "no catalog match"."""
    if should_use_mock_coin_response():
        log_mock_response("lookup_numista")
        return dict(MOCK_NUMISTA)
    if not NUMISTA_API_KEY:
        app.logger.info("[numista] lookup skipped: no NUMISTA_API_KEY configured")
        return None
    if identification.get("identifiable") is False:
        return None

    app.logger.info(
        "[numista] lookup starting for identification: country=%r denomination=%r year=%r grade=%r",
        identification.get("country"), identification.get("denomination"),
        identification.get("year"), identification.get("estimated_grade"),
    )

    candidates = search_numista_types(identification)
    if candidates is None:
        return {"error": "Numista lookup unavailable."}

    best, issue = resolve_numista_type_and_issue(identification, candidates)
    if not best or not issue:
        return None

    type_id = best.get("id")
    detail = fetch_numista_type_detail(type_id) if type_id is not None else None
    merged = {**best, **(detail or {})}
    merged["numista_type_id"] = type_id
    merged["numista_issue_id"] = issue.get("id")
    merged["numista_issue"] = issue
    return merged


# A real UK 2012 20p scan showed the AI's raw grade string ("F-12 (visual
# estimate)") compared for exact equality against Numista's own short
# grade codes ("g"/"vg"/"f"/"vf"/"xf"/"au"/"unc") - which never matches,
# so every real scan fell through to the crude "nearest available" (just
# the middle-indexed priced entry) fallback instead of the actual correct
# grade. The price happened to be identical for F and VF on that coin,
# masking the bug; that won't always be true.
NUMISTA_GRADE_LETTER_ALIASES = {
    "ag": "ag", "g": "g", "vg": "vg", "f": "f", "vf": "vf",
    "xf": "xf", "ef": "xf", "au": "au", "unc": "unc", "ms": "unc", "bu": "unc",
}

# Standard Sheldon-scale numeric grade bands -> Numista's short grade
# code. The number is the authoritative signal when present - XF and EF
# are synonyms for the same 40-49 band, so a numeric lookup handles both
# without needing every letter/number combination spelled out.
_NUMISTA_GRADE_NUMBER_BANDS = (
    (1, 3, "ag"), (4, 7, "g"), (8, 11, "vg"), (12, 19, "f"),
    (20, 39, "vf"), (40, 49, "xf"), (50, 59, "au"), (60, 70, "unc"),
)


def normalize_numista_grade(grade):
    """Canonicalizes a Sheldon-scale grade string (e.g. "F-12 (visual
    estimate)", "VF-25 (visual estimate; not professionally certified)",
    "AU-55", "MS-63", "UNC") to the short grade code Numista's own
    price-list entries use. Explanatory parenthetical suffixes are
    stripped first. Applying this to an already-short code (e.g. "vf") is
    a safe no-op, so it can be used on both the requested grade and each
    price entry's own grade for the comparison."""
    if not grade:
        return ""
    text = re.sub(r"\(.*?\)", "", str(grade)).strip().lower()
    match = re.match(r"([a-z]+)\s*-?\s*(\d+)", text)
    if match:
        value = int(match.group(2))
        for low, high, code in _NUMISTA_GRADE_NUMBER_BANDS:
            if low <= value <= high:
                return code
        return NUMISTA_GRADE_LETTER_ALIASES.get(match.group(1), match.group(1))

    letters_only = re.match(r"([a-z]+)", text)
    if letters_only:
        return NUMISTA_GRADE_LETTER_ALIASES.get(letters_only.group(1), letters_only.group(1))
    return text


def fetch_numista_price(type_id, issue_id, grade):
    try:
        upstream = requests.get(
            f"{NUMISTA_TYPES_URL}/{type_id}/issues/{issue_id}/prices",
            params={"currency": "USD"},
            headers={"Numista-API-Key": NUMISTA_API_KEY},
            timeout=NUMISTA_TIMEOUT,
        )
    except requests.RequestException as error:
        app.logger.error("[numista] price request failed: type_id=%s issue_id=%s error=%s", type_id, issue_id, error)
        return None

    app.logger.info(
        "[numista] price response: type_id=%s issue_id=%s grade=%r status=%s body=%s",
        type_id, issue_id, grade, upstream.status_code, upstream.text[:NUMISTA_LOG_BODY_CHARS],
    )

    if upstream.status_code in (401, 402, 403, 404):
        app.logger.info("[numista] price unavailable for type_id=%s issue_id=%s (status=%s)", type_id, issue_id, upstream.status_code)
        return None
    try:
        upstream.raise_for_status()
        data = upstream.json()
    except (requests.RequestException, ValueError) as error:
        app.logger.error("[numista] price response unusable: type_id=%s issue_id=%s error=%s", type_id, issue_id, error)
        return None

    prices = data.get("prices") if isinstance(data, dict) else None
    if not isinstance(prices, list) or not prices:
        app.logger.info("[numista] price response had no usable 'prices' list: type_id=%s issue_id=%s", type_id, issue_id)
        return None

    grade_text = normalize_numista_grade(grade)
    for entry in prices:
        if isinstance(entry, dict) and normalize_numista_grade(entry.get("grade")) == grade_text and entry.get("price") is not None:
            app.logger.info("[numista] exact grade price match: type_id=%s issue_id=%s grade=%r normalized=%r price=%s", type_id, issue_id, grade, grade_text, entry["price"])
            return {"value": entry["price"], "grade": entry.get("grade"), "exact_grade_match": True}

    priced = [entry for entry in prices if isinstance(entry, dict) and entry.get("price") is not None]
    if not priced:
        app.logger.info("[numista] no priced grade entries found: type_id=%s issue_id=%s", type_id, issue_id)
        return None
    middle = priced[len(priced) // 2]
    app.logger.info(
        "[numista] no exact grade match, using nearest available: type_id=%s issue_id=%s requested_grade=%r used_grade=%r price=%s",
        type_id, issue_id, grade, middle.get("grade"), middle["price"],
    )
    return {"value": middle["price"], "grade": middle.get("grade"), "exact_grade_match": False}


def lookup_pcgs(numista_data):
    if should_use_mock_coin_response():
        log_mock_response("lookup_pcgs")
        return dict(MOCK_PCGS)
    if not PCGS_BEARER_TOKEN or not isinstance(numista_data, dict):
        return None
    references = numista_data.get("references") or []
    pcgs_reference = next((ref for ref in references if ref.get("type") == "PCGS" and ref.get("number")), None)
    if not pcgs_reference:
        app.logger.info("[pcgs] skipped: no PCGS reference number in Numista match")
        return None
    try:
        upstream = requests.get(
            PCGS_PRICE_URL.format(pcgs_number=pcgs_reference["number"]),
            headers={"Authorization": f"bearer {PCGS_BEARER_TOKEN}"},
            timeout=PCGS_TIMEOUT,
        )
        upstream.raise_for_status()
        data = upstream.json()
        if isinstance(data, dict):
            data.setdefault("source_note", "PCGS priceguide lookup by Numista PCGS reference number; this is not automated grading.")
        app.logger.info("[pcgs] lookup succeeded: pcgs_number=%s price=%s", pcgs_reference["number"], data.get("price") if isinstance(data, dict) else None)
        return data
    except (requests.RequestException, ValueError) as error:
        app.logger.warning("[pcgs] lookup failed: pcgs_number=%s error=%s", pcgs_reference["number"], error)
        return {"error": "PCGS lookup unavailable."}


def estimate_value(identification, numista_data):
    """Numista is the primary valuation source. PCGS is an optional fallback.
    Never invents a number - if there's no confident catalog match or no
    usable price, valuation is reported as unavailable."""
    if should_use_mock_coin_response():
        log_mock_response("estimate_value")
        return dict(deterministic_mock_coin_result()["valuation"])

    if identification.get("identifiable") is False:
        return {"status": "unavailable", "currency": "USD", "source": "CoinLens", "reason": "Coin was not identifiable."}

    if not isinstance(numista_data, dict) or numista_data.get("error"):
        app.logger.info("[valuation] unavailable: no confident Numista catalog match")
        return {"status": "unavailable", "currency": "USD", "source": "CoinLens", "reason": "No confident Numista catalog match."}

    type_id = numista_data.get("numista_type_id") or numista_data.get("id")
    issue_id = numista_data.get("numista_issue_id")
    if type_id is None or issue_id is None:
        app.logger.info("[valuation] unavailable: Numista match had no usable type/issue id")
        return {"status": "unavailable", "currency": "USD", "source": "CoinLens", "reason": "No confident Numista catalog match."}

    price = fetch_numista_price(type_id, issue_id, identification.get("estimated_grade"))
    if not price:
        app.logger.info("[valuation] unavailable: Numista match found (type_id=%s issue_id=%s) but no usable price", type_id, issue_id)
        return {"status": "unavailable", "currency": "USD", "source": "Numista", "reason": "Numista match found but no usable price for this grade."}

    app.logger.info("[valuation] available from Numista: type_id=%s issue_id=%s value=%s", type_id, issue_id, price["value"])
    return {
        "status": "available",
        "estimated_value": round(float(price["value"]), 2),
        "currency": "USD",
        "source": "Numista",
        "condition_assumed": price.get("grade") or identification.get("estimated_grade"),
        "grade_matched_exactly": price.get("exact_grade_match", False),
    }


def build_coin_summary(identification, valuation):
    """Templated, not AI-generated - keeps the scan pipeline to a single
    OpenAI call while still giving the UI a human-readable summary."""
    label = " ".join(
        part for part in [identification.get("year"), identification.get("country"), identification.get("denomination")]
        if part and part != "Unknown"
    ) or identification.get("coin_name") or "This coin"

    sentences = [f"This looks like a {label}."]

    grade = identification.get("estimated_grade")
    if grade and grade != "Unknown":
        # The AI is already prompted to embed its own "visual estimate, not
        # a professional certified grade" disclaimer into estimated_grade
        # itself (see IDENTIFICATION_PROMPT) - appending a second one here
        # doubled it up in every real scan (e.g. "VF-25 (visual estimate;
        # not professionally certified) (AI visual estimate, not a
        # professional certified grade).").
        sentences.append(f"Estimated grade: {grade}.")

    if valuation.get("status") == "available" and valuation.get("estimated_value") is not None:
        sentences.append(
            f"Numista-based estimated value: ${valuation['estimated_value']:.2f} {valuation.get('currency', 'USD')}."
        )
    else:
        sentences.append("A reliable market value wasn't available for this specific coin and grade.")

    if identification.get("mint_errors"):
        sentences.append("Possible mint errors were noted - see the details below.")

    return " ".join(sentences)


def build_mock_coin_result(front_image_present=True, back_image_present=False):
    return deterministic_mock_coin_result(front_image_present, back_image_present)


def build_coinlens_result(front_image, back_image=None):
    if should_use_mock_coin_response():
        log_mock_response("/api/identify-coin")
        return build_mock_coin_result(True, back_image is not None)

    identification = identify_coin_with_ai(front_image, back_image)
    app.logger.info(
        "[identify] OpenAI result: status=%s confidence=%s country=%r denomination=%r year=%r grade=%r",
        identification.get("status"), identification.get("confidence"),
        identification.get("country"), identification.get("denomination"),
        identification.get("year"), identification.get("estimated_grade"),
    )
    if identification.get("identifiable") is False:
        return {
            "identification": identification,
            "valuation": {"status": "unavailable", "currency": "USD", "source": "CoinLens", "reason": "Coin was not identifiable."},
            "summary": identification.get("unidentifiable_reason"),
        }

    numista_data = lookup_numista(identification)
    pcgs_data = lookup_pcgs(numista_data)
    valuation = estimate_value(identification, numista_data)
    if valuation.get("status") != "available" and isinstance(pcgs_data, dict) and pcgs_data.get("price") is not None:
        app.logger.info("[valuation] promoted to PCGS fallback: price=%s", pcgs_data["price"])
        valuation = {
            "status": "available",
            "estimated_value": round(float(pcgs_data["price"]), 2),
            "currency": "USD",
            "source": "PCGS",
            "condition_assumed": pcgs_data.get("grade") or identification.get("estimated_grade"),
        }
    app.logger.info(
        "[identify] final valuation: status=%s source=%s value=%s",
        valuation.get("status"), valuation.get("source"), valuation.get("estimated_value"),
    )
    summary = build_coin_summary(identification, valuation)
    return {
        "identification": identification,
        "valuation": valuation,
        "numista": numista_data,
        "pcgs": pcgs_data,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Authoritative persistence (M3)
# ---------------------------------------------------------------------------

# Converts a spelled-out face-value number to digits before
# canonicalize_denomination runs any check, so "five cents" and "5 cents"
# (or "ten cents"/"10 cents", "twenty-five cents"/"25 cents") are always
# handled identically. Previously the nickel/dime/quarter checks matched
# spelled-out face value ("five cent", "ten cent", "twenty-five cent") as
# if it were an explicit coin-type signal, while the digit form ("5
# cents") fell through to the generic slug fallback - the same foreign
# denomination could earn a different (US-specific) badge category
# depending only on whether OpenAI phrased the number as a word or a
# digit. Longest phrases first so "twenty-five"/"twenty five" convert
# before the bare "five" inside them would.
_DENOM_WORD_TO_DIGIT = {
    "twenty-five": "25", "twenty five": "25",
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10", "fifty": "50",
}
_DENOM_WORD_TO_DIGIT_BY_LENGTH = sorted(_DENOM_WORD_TO_DIGIT.items(), key=lambda kv: -len(kv[0]))


def _normalize_denomination_numbers(text):
    for word, digit in _DENOM_WORD_TO_DIGIT_BY_LENGTH:
        text = re.sub(rf"\b{re.escape(word)}\b", digit, text)
    return text


def canonicalize_denomination(denomination, coin_name):
    """Buckets a coin's denomination into the badge taxonomy's vocabulary.
    Never infers a US-specific coin type (nickel/dime/quarter) from face
    value alone - only from an explicit coin-name word - so a foreign 5c/
    10c/25c coin can't earn a US-specific badge just because its value
    happens to match a US coin's value; a genuine US nickel/dime/quarter
    is still recognized because real US coin identifications name the
    coin explicitly (e.g. "Jefferson Nickel", "Roosevelt Dime"). "1
    cent"/"one cent" remains the one explicit numeric exception, since
    that value has no separate US coin name of its own - "penny" is both
    its face value and its name."""
    normalized_denomination = _normalize_denomination_numbers((denomination or "").lower())
    text = f"{normalized_denomination} {(coin_name or '').lower()}"
    if "wheat" in text:
        return "wheat-penny"
    if "penny" in text or re.search(r"\b1\s+cents?\b", text):
        return "penny"
    if "nickel" in text:
        return "nickel"
    if "dime" in text:
        return "dime"
    if "quarter" in text:
        return "quarter"
    if "half dollar" in text or "half-dollar" in text:
        return "half-dollar"
    if "dollar" in text:
        return "dollar"
    slug = re.sub(r"[^a-z0-9]+", "-", normalized_denomination).strip("-")
    return slug or None


def is_foreign_country(country):
    text = _text_of(country)
    if not text:
        return False
    return text not in US_COUNTRY_NAMES


def compute_local_date_hour(tz_offset_minutes):
    """tz_offset_minutes matches JS Date.getTimezoneOffset(): minutes to ADD
    to local time to reach UTC. Falls back to UTC (offset 0) if the client
    didn't send one."""
    try:
        offset = int(tz_offset_minutes)
    except (TypeError, ValueError):
        offset = 0
    offset = max(-14 * 60, min(14 * 60, offset))
    local_dt = datetime.now(timezone.utc) - timedelta(minutes=offset)
    return local_dt.date().isoformat(), local_dt.hour


def parse_year(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def persist_scan(user_id, identification, valuation, source, tz_offset_minutes):
    local_date, local_hour = compute_local_date_hour(tz_offset_minutes)
    payload = {
        "user_id": user_id,
        "coin_name": identification.get("coin_name"),
        "country": identification.get("country"),
        "denomination": identification.get("denomination"),
        "year": parse_year(identification.get("year")),
        "mint_mark": identification.get("mint_mark"),
        "estimated_grade": identification.get("estimated_grade"),
        "estimated_value": valuation.get("estimated_value") if valuation.get("status") == "available" else None,
        "source": source,
        "denom_canonical": canonicalize_denomination(identification.get("denomination"), identification.get("coin_name")),
        "is_foreign": is_foreign_country(identification.get("country")),
        "local_date": local_date,
        "local_hour": local_hour,
    }
    return insert_scan(payload)


# ---------------------------------------------------------------------------
# M6: daily AI-attempt quota (Supabase-backed, survives restarts/multi-worker)
# ---------------------------------------------------------------------------

def daily_window_start_iso():
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def check_and_reserve_quota(user_id):
    """Counts today's AI attempts (successful or not) and, if under the
    limit, reserves this attempt immediately - before OpenAI is called - so a
    burst of concurrent requests can't blow past the limit while each request
    is still waiting on its own OpenAI call."""
    since = daily_window_start_iso()
    try:
        count = count_api_usage_since(user_id, since)
    except SupabaseAdminError as error:
        app.logger.error("quota count failed for user_id=%s: %s", user_id, error)
        raise CoinLensError("quota_check_failed", "Could not verify your usage limit. Try again shortly.", 503)

    if count >= DAILY_SCAN_LIMIT:
        raise CoinLensError(
            "quota_exceeded",
            f"Daily scan limit of {DAILY_SCAN_LIMIT} reached. Try again tomorrow.",
            429,
        )

    try:
        usage_row = insert_api_usage({"user_id": user_id, "endpoint": "identify-coin", "status": "attempted"})
    except SupabaseAdminError as error:
        app.logger.error("quota reserve failed for user_id=%s: %s", user_id, error)
        raise CoinLensError("quota_check_failed", "Could not reserve a scan attempt. Try again shortly.", 503)

    remaining = max(0, DAILY_SCAN_LIMIT - count - 1)
    return usage_row.get("id"), remaining


@app.route("/api/identify-coin", methods=["POST"])
@require_auth
def identify_coin():
    source = read_request_field("source")
    if source not in ("camera", "gallery"):
        return error_response(CoinLensError("invalid_source", "source must be 'camera' or 'gallery'.", 400))

    front_image, back_image = read_identification_images()
    tz_offset_minutes = read_request_field("tz_offset_minutes")

    mock = should_use_mock_coin_response()
    usage_id, remaining = (None, None)
    if not mock:
        usage_id, remaining = check_and_reserve_quota(g.user_id)

    try:
        result = build_coinlens_result(front_image, back_image)
    except CoinLensError:
        update_api_usage(usage_id, {"status": "error"})
        raise

    identification = result.get("identification", {})
    if identification.get("identifiable") is False:
        update_api_usage(usage_id, {"status": "uncertain"})
        body = dict(result)
        if remaining is not None:
            body["remaining_today"] = remaining
        return jsonify(body), 422

    try:
        scan_row = persist_scan(g.user_id, identification, result.get("valuation") or {}, source, tz_offset_minutes)
    except SupabaseAdminError as error:
        app.logger.error("scan insert failed for user_id=%s: %s", g.user_id, error)
        update_api_usage(usage_id, {"status": "error"})
        return error_response(CoinLensError("scan_insert_failed", "Identification succeeded but the scan could not be saved.", 500))

    app.logger.info("[identify] scan persisted: id=%s user_id=%s source=%s", scan_row.get("id"), g.user_id, source)
    update_api_usage(usage_id, {"status": "identified", "scan_id": scan_row.get("id")})

    body = dict(result)
    body["scan"] = scan_row
    if remaining is not None:
        body["remaining_today"] = remaining
    return jsonify(body)


@app.route("/api/generate-ebay-listing", methods=["POST"])
@require_auth
def generate_ebay_listing():
    if not ENABLE_EBAY_LISTING:
        return jsonify({
            "feature_disabled": True,
            "feature": "ebay_listing",
            "message": "eBay listing generation is disabled in this version.",
        }), 200

    payload = request.get_json(force=True, silent=True) or {}
    if should_use_mock_coin_response():
        log_mock_response("/api/generate-ebay-listing")
        return jsonify(dict(MOCK_EBAY_LISTING))

    try:
        prompt = f"""You are an expert eBay copywriter for collectible coins. Create a polished listing draft.

Coin data: {json.dumps(payload.get("identification") or payload.get("coinData"))}
Numista specs: {json.dumps(payload.get("numista") or payload.get("numistaData"))}
Value estimate: {json.dumps(payload.get("valuation") or payload.get("valueEstimate"))}
Summary: {payload.get("summary") or "No summary available"}

Return ONLY a raw JSON object with these exact keys:
- "title": string
- "subtitle": string
- "description": string
- "item_specifics": array of objects with "label" and "value"
- "shipping_notes": string"""
        return jsonify(extract_json(openai_chat_content([{"role": "user", "content": prompt}], 800)))
    except CoinLensError as error:
        return error_response(error)


@app.route("/api/numista-specs", methods=["GET"])
def numista_specs():
    if should_use_mock_coin_response():
        log_mock_response("/api/numista-specs")
        return jsonify({"items": [dict(MOCK_NUMISTA)], "marker": MOCK_MARKER})

    if not NUMISTA_API_KEY:
        return jsonify({"items": []})

    upstream = requests.get(
        NUMISTA_COINS_URL,
        params={"q": request.args.get("q", ""), "count": request.args.get("count", 1)},
        headers={"Numista-API-Key": NUMISTA_API_KEY},
        timeout=NUMISTA_TIMEOUT,
    )
    return proxy_response(upstream)


@app.route("/api/pcgs-value/<pcgs_number>", methods=["GET"])
def pcgs_value(pcgs_number):
    if should_use_mock_coin_response():
        log_mock_response("/api/pcgs-value")
        payload = dict(MOCK_PCGS)
        payload["pcgs_number"] = pcgs_number
        return jsonify(payload)

    if not PCGS_BEARER_TOKEN:
        return jsonify(None)

    upstream = requests.get(
        PCGS_PRICE_URL.format(pcgs_number=pcgs_number),
        headers={"Authorization": f"bearer {PCGS_BEARER_TOKEN}"},
        timeout=PCGS_TIMEOUT,
    )
    return proxy_response(upstream)


@app.route("/api/log-scan", methods=["POST"])
def log_scan():
    if should_use_mock_coin_response():
        log_mock_response("/api/log-scan")
        return jsonify({"success": True, "marker": MOCK_MARKER})

    if not SHEETDB_URL:
        return jsonify({"skipped": True})

    payload = request.get_json(force=True, silent=True) or {}
    upstream = requests.post(SHEETDB_URL, json=payload, timeout=REQUEST_TIMEOUT)
    return proxy_response(upstream)


@app.route("/api/scans", methods=["GET"])
def get_scans():
    if should_use_mock_coin_response():
        log_mock_response("/api/scans")
        return jsonify([dict(MOCK_SCAN_ROW)])

    if not SHEETDB_URL:
        return jsonify([])

    upstream = requests.get(SHEETDB_URL, timeout=REQUEST_TIMEOUT)
    return proxy_response(upstream)


@app.route("/api/test-scan", methods=["POST"])
@require_user
def test_scan():
    payload = {
        "user_id": g.user_id,
        "coin_name": "Lincoln Wheat Cent",
        "year": 1946,
        "estimated_value": 0.20,
        "source": "camera",
    }
    try:
        row = insert_scan(payload)
    except SupabaseAdminError as error:
        app.logger.error("test_scan insert failed for user_id=%s: %s", g.user_id, error)
        return jsonify({"error": {"code": "scan_insert_failed", "message": "Could not save scan."}}), 500

    app.logger.info("test_scan created scan id=%s for user_id=%s", row.get("id"), g.user_id)
    return jsonify(row), 201


@app.route("/api/verify-admin-code", methods=["POST"])
def verify_admin_code():
    payload = request.get_json(force=True, silent=True) or {}
    submitted = str(payload.get("code", "")).strip()
    valid = bool(ADMIN_CODE) and submitted == ADMIN_CODE
    return jsonify({"valid": valid})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
