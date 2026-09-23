import os
from functools import wraps

import jwt
from flask import g, jsonify, request

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
ALLOWED_ALGORITHMS = ["ES256", "RS256"]

_jwk_client = None


def _jwks_url():
    return f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"


def _issuer():
    return f"{SUPABASE_URL}/auth/v1"


def _get_jwk_client():
    global _jwk_client
    if _jwk_client is None:
        _jwk_client = jwt.PyJWKClient(_jwks_url())
    return _jwk_client


def _get_signing_key(token):
    return _get_jwk_client().get_signing_key_from_jwt(token).key


def verify_access_token(token):
    signing_key = _get_signing_key(token)
    return jwt.decode(
        token,
        signing_key,
        algorithms=ALLOWED_ALGORITHMS,
        audience="authenticated",
        issuer=_issuer(),
    )


def _auth_error(code, message, status):
    return jsonify({"error": {"code": code, "message": message}}), status


def require_auth(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not SUPABASE_URL:
            return _auth_error("auth_unconfigured", "Server is missing SUPABASE_URL.", 500)

        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return _auth_error("auth_missing", "Sign in required.", 401)

        token = header[len("Bearer "):].strip()
        if not token:
            return _auth_error("auth_missing", "Sign in required.", 401)

        try:
            claims = verify_access_token(token)
        except jwt.PyJWTError:
            return _auth_error("auth_invalid", "Your session has expired. Sign in again.", 401)

        g.user_id = claims.get("sub")
        return view_func(*args, **kwargs)

    return wrapper
