import os

import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
# Prefer the new Supabase secret key naming; fall back to the legacy service-role key.
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

REQUEST_TIMEOUT = 10


class SupabaseAdminError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def _admin_key():
    return SUPABASE_SECRET_KEY or SUPABASE_SERVICE_ROLE_KEY


def _require_config():
    if not SUPABASE_URL or not _admin_key():
        raise SupabaseAdminError("Server is missing Supabase admin configuration.")


def insert_scan(*, user_id, coin_name, country, denomination, year, mint_mark, estimated_grade, source, estimated_value=None):
    """Insert one authoritative scan row using the server-only Supabase admin credential.

    Never called with a client-supplied user_id: callers must pass the trusted
    id from the verified auth token (e.g. g.user_id).
    """
    _require_config()

    payload = {
        "user_id": user_id,
        "coin_name": coin_name,
        "country": country,
        "denomination": denomination,
        "year": year,
        "mint_mark": mint_mark,
        "estimated_grade": estimated_grade,
        "source": source,
        "estimated_value": estimated_value,
    }

    admin_key = _admin_key()
    try:
        response = requests.post(
            f"{SUPABASE_URL}/rest/v1/scans",
            headers={
                "apikey": admin_key,
                "Authorization": f"Bearer {admin_key}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as error:
        raise SupabaseAdminError("Could not reach Supabase to save the scan.") from error

    if not response.ok:
        raise SupabaseAdminError(f"Supabase rejected the scan insert (status {response.status_code}).")

    try:
        rows = response.json()
    except ValueError as error:
        raise SupabaseAdminError("Supabase returned an unreadable response for the scan insert.") from error

    if not rows:
        raise SupabaseAdminError("Supabase did not return the inserted scan row.")

    return rows[0]
