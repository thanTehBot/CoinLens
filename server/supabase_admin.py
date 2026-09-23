"""Supabase server-side client for trusted backend writes.

This client authenticates with the Supabase service-role key, which BYPASSES
Row Level Security. It must only be used for writes that the server has itself
validated. It must never be used to read data on behalf of a user: user reads
go through Expo with the user's own JWT.
"""

import logging
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

REQUEST_TIMEOUT = 10

# Supabase's own REST gateway occasionally returns one of these on a transient
# infrastructure blip (e.g. a cold project waking up), not because the
# request itself was bad - safe to retry a couple of times with a short
# backoff rather than fail a whole scan over it.
RETRYABLE_GATEWAY_STATUSES = (502, 503, 504)
MAX_GATEWAY_RETRIES = 2
RETRY_BACKOFF_SECONDS = 0.5

logger = logging.getLogger(__name__)


class SupabaseAdminError(RuntimeError):
    """Raised when a trusted server-side Supabase write cannot be completed."""


def _headers():
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _require_config():
    if not SUPABASE_URL:
        raise SupabaseAdminError("SUPABASE_URL environment variable is missing.")
    if not SUPABASE_SERVICE_ROLE_KEY:
        raise SupabaseAdminError("SUPABASE_SERVICE_ROLE_KEY environment variable is missing.")


def _request_with_gateway_retry(method, *args, **kwargs):
    """Calls ``method(*args, **kwargs)`` (a ``requests`` verb function),
    retrying up to ``MAX_GATEWAY_RETRIES`` times if Supabase's gateway
    responds with a transient 502/503/504. Any other status (including a
    real 4xx/2xx) is returned immediately without retrying."""
    attempt = 0
    while True:
        response = method(*args, **kwargs)
        if response.status_code not in RETRYABLE_GATEWAY_STATUSES or attempt >= MAX_GATEWAY_RETRIES:
            return response
        attempt += 1
        logger.warning(
            "supabase request got a transient %s, retrying (attempt %s/%s): %s",
            response.status_code, attempt, MAX_GATEWAY_RETRIES, args[0] if args else kwargs.get("url"),
        )
        time.sleep(RETRY_BACKOFF_SECONDS * attempt)


def insert_scan(payload: dict) -> dict:
    """Insert a row into the ``scans`` table and return the created row.

    Raises ``SupabaseAdminError`` if the client is not configured or if Supabase
    responds with any non-2xx status.
    """
    _require_config()

    url = f"{SUPABASE_URL}/rest/v1/scans"

    try:
        response = _request_with_gateway_retry(
            requests.post,
            url,
            json=payload,
            headers=_headers(),
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as error:
        logger.error("supabase insert_scan request failed: %s", error)
        raise SupabaseAdminError(f"scans insert request failed: {error}") from error

    if not response.ok:
        logger.error(
            "supabase insert_scan failed: status=%s body=%s",
            response.status_code,
            response.text[:500],
        )
        raise SupabaseAdminError(
            f"scans insert failed: status={response.status_code} body={response.text[:500]}"
        )

    try:
        data = response.json()
    except ValueError as error:
        logger.error(
            "supabase insert_scan returned an unreadable body: status=%s body=%s",
            response.status_code,
            response.text[:500],
        )
        raise SupabaseAdminError(
            f"scans insert returned an unreadable body: status={response.status_code}"
        ) from error

    if isinstance(data, list):
        if not data:
            raise SupabaseAdminError("scans insert returned no row.")
        return data[0]
    return data


def _first_row_or_dict(data, context):
    if isinstance(data, list):
        if not data:
            raise SupabaseAdminError(f"{context} returned no row.")
        return data[0]
    return data


def count_api_usage_since(user_id: str, since_iso: str) -> int:
    """Count api_usage rows for a user at/after ``since_iso`` (server-only)."""
    _require_config()

    url = f"{SUPABASE_URL}/rest/v1/api_usage"
    headers = _headers()
    headers["Prefer"] = "count=exact"

    try:
        response = _request_with_gateway_retry(
            requests.get,
            url,
            params={
                "user_id": f"eq.{user_id}",
                "created_at": f"gte.{since_iso}",
                "select": "id",
                "limit": "1",
            },
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as error:
        logger.error("supabase count_api_usage_since request failed: %s", error)
        raise SupabaseAdminError(f"api_usage count request failed: {error}") from error

    if not response.ok:
        logger.error(
            "supabase count_api_usage_since failed: status=%s body=%s",
            response.status_code,
            response.text[:500],
        )
        raise SupabaseAdminError(
            f"api_usage count failed: status={response.status_code} body={response.text[:500]}"
        )

    content_range = response.headers.get("Content-Range", "")
    if "/" in content_range:
        total = content_range.rsplit("/", 1)[-1]
        if total.isdigit():
            return int(total)

    try:
        return len(response.json() or [])
    except ValueError:
        return 0


def insert_api_usage(payload: dict) -> dict:
    """Insert a row into ``api_usage`` and return the created row (server-only)."""
    _require_config()

    url = f"{SUPABASE_URL}/rest/v1/api_usage"
    try:
        response = _request_with_gateway_retry(
            requests.post, url, json=payload, headers=_headers(), timeout=REQUEST_TIMEOUT
        )
    except requests.RequestException as error:
        logger.error("supabase insert_api_usage request failed: %s", error)
        raise SupabaseAdminError(f"api_usage insert request failed: {error}") from error

    if not response.ok:
        logger.error(
            "supabase insert_api_usage failed: status=%s body=%s",
            response.status_code,
            response.text[:500],
        )
        raise SupabaseAdminError(
            f"api_usage insert failed: status={response.status_code} body={response.text[:500]}"
        )

    try:
        data = response.json()
    except ValueError as error:
        raise SupabaseAdminError("api_usage insert returned an unreadable body.") from error

    return _first_row_or_dict(data, "api_usage insert")


def fetch_scans_for_user(user_id: str, columns: str) -> list:
    """Reads one user's own scans (service-role, server-only) - used to
    compute that same authenticated user's own badge eligibility. Never
    used to read a different user's scans for direct display."""
    _require_config()
    url = f"{SUPABASE_URL}/rest/v1/scans"
    try:
        response = _request_with_gateway_retry(
            requests.get, url,
            params={"user_id": f"eq.{user_id}", "select": columns, "order": "scanned_at.asc"},
            headers=_headers(), timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as error:
        logger.error("supabase fetch_scans_for_user request failed: %s", error)
        raise SupabaseAdminError(f"scans fetch request failed: {error}") from error

    if not response.ok:
        logger.error(
            "supabase fetch_scans_for_user failed: status=%s body=%s",
            response.status_code, response.text[:500],
        )
        raise SupabaseAdminError(
            f"scans fetch failed: status={response.status_code} body={response.text[:500]}"
        )
    try:
        return response.json() or []
    except ValueError as error:
        raise SupabaseAdminError("scans fetch returned an unreadable body.") from error


def fetch_scans_for_users(user_ids: list, columns: str) -> list:
    """Batched read of scans for MULTIPLE users at once (service-role,
    server-only) - lets the leaderboard compute every user's badge count
    with one query instead of one per user. Ordered by scanned_at
    ascending (streak-based badge checks depend on this); grouping the
    single ordered result by user_id afterward preserves each user's own
    ascending order. The raw rows this returns must never be sent to any
    client - only badge counts derived from them may leave the server."""
    if not user_ids:
        return []
    _require_config()
    url = f"{SUPABASE_URL}/rest/v1/scans"
    try:
        response = _request_with_gateway_retry(
            requests.get, url,
            params={"user_id": f"in.({','.join(user_ids)})", "select": columns, "order": "scanned_at.asc"},
            headers=_headers(), timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as error:
        logger.error("supabase fetch_scans_for_users request failed: %s", error)
        raise SupabaseAdminError(f"scans batch fetch request failed: {error}") from error

    if not response.ok:
        logger.error(
            "supabase fetch_scans_for_users failed: status=%s body=%s",
            response.status_code, response.text[:500],
        )
        raise SupabaseAdminError(
            f"scans batch fetch failed: status={response.status_code} body={response.text[:500]}"
        )
    try:
        return response.json() or []
    except ValueError as error:
        raise SupabaseAdminError("scans batch fetch returned an unreadable body.") from error


def fetch_profile_created_at(user_id: str):
    """Reads one user's own profiles.created_at (service-role) - the
    trusted membership-date source for badge evaluation. Always derived
    from the authenticated user's own JWT-verified id, never a
    client-supplied one."""
    _require_config()
    url = f"{SUPABASE_URL}/rest/v1/profiles"
    try:
        response = _request_with_gateway_retry(
            requests.get, url,
            params={"id": f"eq.{user_id}", "select": "created_at"},
            headers=_headers(), timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as error:
        logger.error("supabase fetch_profile_created_at request failed: %s", error)
        raise SupabaseAdminError(f"profile fetch request failed: {error}") from error

    if not response.ok:
        logger.error(
            "supabase fetch_profile_created_at failed: status=%s body=%s",
            response.status_code, response.text[:500],
        )
        raise SupabaseAdminError(
            f"profile fetch failed: status={response.status_code} body={response.text[:500]}"
        )
    try:
        rows = response.json() or []
    except ValueError as error:
        raise SupabaseAdminError("profile fetch returned an unreadable body.") from error
    return rows[0].get("created_at") if rows else None


def fetch_leaderboard_rows() -> list:
    """Calls the existing leaderboard() RPC with the service-role client -
    the same safe aggregate rows the client already reads directly
    (user_id/display_name/scan_count/total_value/avg_value/member_since),
    just also readable server-side so /api/leaderboard can attach an
    authoritative badge_count to each row without weakening what the RPC
    itself exposes."""
    _require_config()
    url = f"{SUPABASE_URL}/rest/v1/rpc/leaderboard"
    try:
        response = _request_with_gateway_retry(
            requests.post, url, json={}, headers=_headers(), timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as error:
        logger.error("supabase fetch_leaderboard_rows request failed: %s", error)
        raise SupabaseAdminError(f"leaderboard RPC request failed: {error}") from error

    if not response.ok:
        logger.error(
            "supabase fetch_leaderboard_rows failed: status=%s body=%s",
            response.status_code, response.text[:500],
        )
        raise SupabaseAdminError(
            f"leaderboard RPC failed: status={response.status_code} body={response.text[:500]}"
        )
    try:
        return response.json() or []
    except ValueError as error:
        raise SupabaseAdminError("leaderboard RPC returned an unreadable body.") from error


def update_api_usage(usage_id: str, payload: dict) -> None:
    """Best-effort update of an api_usage row's outcome. Never raises: this is
    bookkeeping for the daily quota count, not something a request should fail
    over if it can't be written."""
    if not usage_id:
        return
    try:
        _require_config()
        url = f"{SUPABASE_URL}/rest/v1/api_usage?id=eq.{usage_id}"
        response = requests.patch(url, json=payload, headers=_headers(), timeout=REQUEST_TIMEOUT)
        if not response.ok:
            logger.warning(
                "supabase update_api_usage failed: status=%s body=%s",
                response.status_code,
                response.text[:300],
            )
    except (requests.RequestException, SupabaseAdminError) as error:
        logger.warning("supabase update_api_usage failed: %s", error)
