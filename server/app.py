import os
import base64
import binascii
import json
import logging

import requests
from dotenv import load_dotenv
from flask import Flask, Response, g, jsonify, request
from flask_cors import CORS

from auth import require_auth
from require_user import require_user
import supabase_admin
from mock_openai import (
    MOCK_EBAY_LISTING,
    MOCK_MARKER,
    MOCK_NUMISTA,
    MOCK_PCGS,
    MOCK_SCAN_ROW,
    build_mock_coin_result as deterministic_mock_coin_result,
    build_mock_reply,
)

load_dotenv()

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
NUMISTA_API_KEY = os.environ.get("NUMISTA_API_KEY", "")
PCGS_BEARER_TOKEN = os.environ.get("PCGS_BEARER_TOKEN", "")
SHEETDB_URL = os.environ.get("SHEETDB_URL", "")
ADMIN_CODE = os.environ.get("ADMIN_CODE", "")
MOCK_MODE = os.environ.get("MOCK_MODE", "false").lower() == "true"
USE_MOCK_COIN_RESPONSE = os.environ.get("USE_MOCK_COIN_RESPONSE", "false").lower() == "true" or MOCK_MODE

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
NUMISTA_COINS_URL = "https://api.numista.com/api/v3/coins"
PCGS_PRICE_URL = "https://api.pcgs.com/publicapi/priceguide/getpricedata/{pcgs_number}"

REQUEST_TIMEOUT = 60

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
app.logger.handlers = logging.getLogger("gunicorn.error").handlers or app.logger.handlers
app.logger.setLevel(logging.getLogger("gunicorn.error").level or logging.INFO)


class CoinLensError(Exception):
    def __init__(self, code, message, status=500):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


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
    return jsonify({"error": {"code": error.code, "message": error.message}}), error.status


@app.errorhandler(CoinLensError)
def handle_coinlens_error(error):
    return error_response(error)


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


@app.route("/api/openai/chat", methods=["POST"])
@require_auth
def openai_chat():
    payload = request.get_json(force=True, silent=True) or {}

    if should_use_mock_coin_response():
        log_mock_response("/api/openai/chat")
        content = build_mock_reply(payload)
        return jsonify({"choices": [{"message": {"content": content}}]})

    if not OPENAI_API_KEY:
        return jsonify({"error": {"message": "Server is missing OPENAI_API_KEY."}}), 500

    upstream = requests.post(
        OPENAI_CHAT_URL,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}",
        },
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    return proxy_response(upstream)


def get_model_candidates(primary_model):
    if not primary_model:
        return ["gpt-4o-mini"]
    if primary_model == "gpt-4o":
        return ["gpt-4o", "gpt-4o-mini"]
    return [primary_model]


def is_retryable_openai_error(status, message):
    text = (message or "").lower()
    return status in (400, 403, 404, 429) or "model" in text or "unsupported" in text or "not found" in text


def openai_chat_content(messages, max_tokens=400, model="gpt-4o-mini"):
    if not OPENAI_API_KEY:
        raise CoinLensError("key_missing", "Server is missing OPENAI_API_KEY.", 500)

    candidates = get_model_candidates(model)
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
                timeout=REQUEST_TIMEOUT,
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
            if is_retryable_openai_error(upstream.status_code, message) and index < len(candidates) - 1:
                last_error = CoinLensError("upstream_failure", "AI provider rejected the requested model.", 502)
                continue
            if upstream.status_code == 401:
                raise CoinLensError("key_invalid", "AI provider rejected the API key.", 401)
            if upstream.status_code == 429:
                code = "quota" if "quota" in message.lower() or "billing" in message.lower() else "rate_limit"
                raise CoinLensError(code, "AI provider rate or quota limit reached.", 429)
            if upstream.status_code == 402:
                raise CoinLensError("quota", "AI provider billing limit reached.", 402)
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


VALID_SCAN_SOURCES = {"camera", "gallery"}


def read_scan_source():
    # Ownership never comes from the body; only this route's own source label does.
    # Any client-supplied user_id here is ignored - trust g.user_id from require_auth instead.
    if request.files:
        source = request.form.get("source")
    else:
        payload = request.get_json(force=True, silent=True) or {}
        source = payload.get("source")

    if source not in VALID_SCAN_SOURCES:
        raise CoinLensError("invalid_source", "source must be 'camera' or 'gallery'.", 400)
    return source


def parse_scan_year(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def normalize_identification(data):
    if not isinstance(data, dict):
        raise CoinLensError("malformed_ai_response", "AI identification was not an object.", 502)

    identifiable = data.get("identifiable", True)
    if identifiable is False:
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
            "identifiable": False,
            "unidentifiable_reason": data.get("unidentifiable_reason") or "The coin could not be identified confidently.",
            "confidence": int(data.get("confidence") or 0),
            "alternatives": data.get("alternatives") if isinstance(data.get("alternatives"), list) else [],
        }

    country = str(data.get("country") or "Unknown").strip() or "Unknown"
    denomination = str(data.get("denomination") or "Unknown").strip() or "Unknown"
    year = str(data.get("year") or "Unknown").strip() or "Unknown"
    coin_name = data.get("coin_name") or " ".join(part for part in [year, country, denomination] if part and part != "Unknown") or "Identified coin"
    confidence = data.get("confidence", 0)
    try:
        confidence = max(0, min(100, int(confidence)))
    except (TypeError, ValueError):
        confidence = 0

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
        "identifiable": True,
        "confidence": confidence,
        "alternatives": data.get("alternatives") if isinstance(data.get("alternatives"), list) else [],
    }


def build_identification_messages(front_image, back_image=None):
    visual_prompt = """You are an expert numismatist examining a coin. Describe everything you can see in exhaustive detail:
- Obverse/front and reverse/back designs, portraits, inscriptions, mottos
- Date and mint mark, using exact visible characters
- Country and denomination text
- Metal color and composition clues
- Surface condition: luster, wear, contact marks, scratches, toning
- Doubling, off-center strike, planchet irregularities, die cracks, or other anomalies
- Overall grade estimate using the Sheldon scale
Be specific and literal. Describe exactly what you observe, not what you assume."""

    content = [{"type": "text", "text": visual_prompt}, {"type": "image_url", "image_url": {"url": front_image["data_url"], "detail": "high"}}]
    if back_image:
        content.append({"type": "image_url", "image_url": {"url": back_image["data_url"], "detail": "high"}})
    return [{"role": "user", "content": content}]


def identify_with_ai(front_image, back_image=None):
    description = openai_chat_content(build_identification_messages(front_image, back_image), 800, "gpt-4o")
    extraction_prompt = f"""Based on this numismatist's description of a coin, return ONLY a raw JSON object with these exact keys:
- "country": string
- "denomination": string
- "year": string
- "mint_mark": string or null
- "estimated_grade": string
- "mint_errors": array of strings
- "varieties": string or null
- "error_premium": boolean
- "special_notes": string
- "identifiable": boolean
- "unidentifiable_reason": string, only when identifiable is false
- "confidence": integer 0-100
- "alternatives": array of up to 3 objects with "coin" and "confidence"

Description:
{description}"""
    return normalize_identification(extract_json(openai_chat_content([{"role": "user", "content": extraction_prompt}], 600)))


def lookup_numista(identification):
    if should_use_mock_coin_response():
        log_mock_response("lookup_numista")
        return dict(MOCK_NUMISTA)
    if not NUMISTA_API_KEY or identification.get("identifiable") is False:
        return None
    query = " ".join(filter(None, [identification.get("country"), identification.get("denomination"), identification.get("year")])).strip()
    if not query:
        return None
    try:
        upstream = requests.get(
            NUMISTA_COINS_URL,
            params={"q": query, "count": 1},
            headers={"Numista-API-Key": NUMISTA_API_KEY},
            timeout=REQUEST_TIMEOUT,
        )
        upstream.raise_for_status()
        return (upstream.json().get("items") or [None])[0]
    except (requests.RequestException, ValueError):
        return {"error": "Numista lookup unavailable."}


def lookup_pcgs(numista_data):
    if should_use_mock_coin_response():
        log_mock_response("lookup_pcgs")
        return dict(MOCK_PCGS)
    if not PCGS_BEARER_TOKEN or not isinstance(numista_data, dict):
        return None
    references = numista_data.get("references") or []
    pcgs_reference = next((ref for ref in references if ref.get("type") == "PCGS" and ref.get("number")), None)
    if not pcgs_reference:
        return None
    try:
        upstream = requests.get(
            PCGS_PRICE_URL.format(pcgs_number=pcgs_reference["number"]),
            headers={"Authorization": f"bearer {PCGS_BEARER_TOKEN}"},
            timeout=REQUEST_TIMEOUT,
        )
        upstream.raise_for_status()
        data = upstream.json()
        if isinstance(data, dict):
            data.setdefault("source_note", "PCGS priceguide lookup by Numista PCGS reference number; this is not automated grading.")
        return data
    except (requests.RequestException, ValueError):
        return {"error": "PCGS lookup unavailable."}


def estimate_value(identification, numista_data):
    if should_use_mock_coin_response():
        log_mock_response("estimate_value")
        return dict(deterministic_mock_coin_result()["valuation"])
    if identification.get("identifiable") is False:
        return {"status": "unavailable", "currency": "USD", "source": "CoinLens", "reason": "Coin was not identifiable."}
    try:
        prompt = f"""You are an expert numismatist with deep knowledge of auction results and retail prices. Estimate this coin's current market value.

Coin data: {json.dumps(identification)}
Numista specs: {json.dumps(numista_data)}

Return ONLY a raw JSON object with keys:
- "low": lowest realistic retail/auction value in USD, number
- "high": highest realistic retail/auction value in USD, number
- "condition_assumed": grade/condition used
- "error_value_note": string or null
- "reasoning": 1-2 sentences"""
        data = extract_json(openai_chat_content([{"role": "user", "content": prompt}], 350, "gpt-4o"))
        low = data.get("low")
        high = data.get("high")
        estimated = None
        if isinstance(low, (int, float)) and isinstance(high, (int, float)):
            estimated = round((low + high) / 2, 2)
        data.update({"status": "available", "estimated_value": estimated, "currency": "USD", "source": "AI estimate"})
        return data
    except CoinLensError:
        return {"status": "unavailable", "currency": "USD", "source": "AI estimate", "reason": "Valuation unavailable."}


def generate_coin_summary(identification, numista_data, pcgs_data):
    if should_use_mock_coin_response():
        log_mock_response("generate_coin_summary")
        return deterministic_mock_coin_result()["summary"]
    try:
        prompt = f"""You are a friendly numismatist app. Write 3 exciting sentences about this coin for a beginner.
AI ID: {json.dumps(identification)}
Numista: {json.dumps(numista_data)}
PCGS: {json.dumps(pcgs_data)}"""
        return openai_chat_content([{"role": "user", "content": prompt}], 200)
    except CoinLensError:
        return None


def build_mock_coin_result(front_image_present=True, back_image_present=False):
    return deterministic_mock_coin_result(front_image_present, back_image_present)


def build_coinlens_result(front_image, back_image=None):
    if should_use_mock_coin_response():
        log_mock_response("/api/identify-coin")
        return build_mock_coin_result(True, back_image is not None)
    identification = identify_with_ai(front_image, back_image)
    if identification.get("identifiable") is False:
        return {
            "identification": identification,
            "valuation": {"status": "unavailable", "currency": "USD", "source": "CoinLens", "reason": "Coin was not identifiable."},
            "summary": identification.get("unidentifiable_reason"),
        }
    numista_data = lookup_numista(identification)
    pcgs_data = lookup_pcgs(numista_data)
    valuation = estimate_value(identification, numista_data)
    summary = generate_coin_summary(identification, numista_data, pcgs_data)
    return {
        "identification": identification,
        "valuation": valuation,
        "numista": numista_data,
        "pcgs": pcgs_data,
        "summary": summary,
    }


@app.route("/api/identify-coin", methods=["POST"])
@require_auth
def identify_coin():
    front_image, back_image = read_identification_images()
    source = read_scan_source()
    result = build_coinlens_result(front_image, back_image)

    identification = result.get("identification") or {}
    if identification.get("identifiable") is False:
        return jsonify(result), 422

    # Mock/deterministic responses are not a real identification - never persist them as a scan.
    if not should_use_mock_coin_response():
        try:
            scan_row = supabase_admin.insert_scan(
                user_id=g.user_id,
                coin_name=identification.get("coin_name"),
                country=identification.get("country"),
                denomination=identification.get("denomination"),
                year=parse_scan_year(identification.get("year")),
                mint_mark=identification.get("mint_mark"),
                estimated_grade=identification.get("estimated_grade"),
                source=source,
                estimated_value=None,
            )
        except supabase_admin.SupabaseAdminError as error:
            app.logger.error("Failed to persist scan for user_id=%s: %s", g.user_id, error)
            raise CoinLensError("scan_persist_failed", "Coin was identified, but saving the scan failed. Try again.", 502)
        result = {**result, "scan_row": scan_row}

    return jsonify(result)


@app.route("/api/generate-ebay-listing", methods=["POST"])
@require_auth
def generate_ebay_listing():
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
        return jsonify(extract_json(openai_chat_content([{"role": "user", "content": prompt}], 800, "gpt-4o")))
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
        timeout=REQUEST_TIMEOUT,
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
        timeout=REQUEST_TIMEOUT,
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


@app.route("/api/verify-admin-code", methods=["POST"])
def verify_admin_code():
    payload = request.get_json(force=True, silent=True) or {}
    submitted = str(payload.get("code", "")).strip()
    valid = bool(ADMIN_CODE) and submitted == ADMIN_CODE
    return jsonify({"valid": valid})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
