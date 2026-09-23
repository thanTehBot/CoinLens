import os
from functools import wraps

import requests
from dotenv import load_dotenv
from flask import current_app, g, jsonify, request

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY environment variables are required.")

SUPABASE_USER_URL = f"{SUPABASE_URL}/auth/v1/user"
REQUEST_TIMEOUT = 10


def _reject_unauthorized():
    return jsonify({"error": {"code": "auth_invalid", "message": "Sign in required."}}), 401


def require_user(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return _reject_unauthorized()

        token = header[len("Bearer "):].strip()
        if not token:
            return _reject_unauthorized()

        try:
            response = requests.get(
                SUPABASE_USER_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "apikey": SUPABASE_ANON_KEY,
                },
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as error:
            current_app.logger.warning("Supabase auth request failed: %s", error)
            return _reject_unauthorized()

        if response.status_code != 200:
            current_app.logger.warning(
                "Supabase auth rejected token: status=%s body=%s",
                response.status_code,
                response.text[:200],
            )
            return _reject_unauthorized()

        try:
            data = response.json()
        except ValueError:
            current_app.logger.warning("Supabase auth returned an unreadable response body")
            return _reject_unauthorized()

        user_id = data.get("id")
        user_email = data.get("email")

        g.user_id = user_id
        g.user_email = user_email
        current_app.logger.info("Authenticated request for user_id=%s", user_id)

        return view_func(*args, **kwargs)

    return wrapper
