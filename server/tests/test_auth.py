import base64
import os
import sys
import time
import unittest
from unittest import mock

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

SERVER_DIR = os.path.dirname(os.path.dirname(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import app as coinlens_app
import auth as coinlens_auth


JPEG_BASE64 = base64.b64encode(b"\xff\xd8\xff\xe0coinlens-test-image").decode("ascii")
TEST_SUPABASE_URL = "https://test.supabase.co"
TEST_ISSUER = f"{TEST_SUPABASE_URL}/auth/v1"


def make_test_token(sub="user-123", aud="authenticated", issuer=TEST_ISSUER, exp_delta=3600):
    private_key = ec.generate_private_key(ec.SECP256R1())
    now = int(time.time())
    claims = {"sub": sub, "aud": aud, "iss": issuer, "iat": now, "exp": now + exp_delta}
    token = jwt.encode(claims, private_key, algorithm="ES256")
    return token, private_key.public_key()


class RequireAuthTests(unittest.TestCase):
    def setUp(self):
        self.client = coinlens_app.app.test_client()
        coinlens_app.USE_MOCK_COIN_RESPONSE = True
        self._original_supabase_url = coinlens_auth.SUPABASE_URL
        coinlens_auth.SUPABASE_URL = TEST_SUPABASE_URL

    def tearDown(self):
        coinlens_auth.SUPABASE_URL = self._original_supabase_url

    def test_missing_auth_header_rejected(self):
        response = self.client.post("/api/identify-coin", json={"front_image": JPEG_BASE64})
        body = response.get_json()

        self.assertEqual(response.status_code, 401)
        self.assertEqual(body["error"]["code"], "auth_missing")

    def test_invalid_token_rejected(self):
        response = self.client.post(
            "/api/identify-coin",
            json={"front_image": JPEG_BASE64},
            headers={"Authorization": "Bearer not-a-real-jwt"},
        )
        body = response.get_json()

        self.assertEqual(response.status_code, 401)
        self.assertEqual(body["error"]["code"], "auth_invalid")

    def test_valid_token_allowed(self):
        token, public_key = make_test_token()
        with mock.patch.object(coinlens_auth, "_get_signing_key", return_value=public_key), \
             mock.patch.object(coinlens_app, "insert_scan", return_value={"id": "scan-1", "user_id": "user-123"}):
            response = self.client.post(
                "/api/identify-coin",
                json={"front_image": JPEG_BASE64, "source": "camera"},
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(response.status_code, 200)

    def test_health_still_public(self):
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])

    def test_mock_mode_with_authenticated_request_skips_openai(self):
        token, public_key = make_test_token()
        with mock.patch.object(coinlens_auth, "_get_signing_key", return_value=public_key), \
             mock.patch.object(coinlens_app.requests, "post", side_effect=AssertionError("should not call OpenAI")), \
             mock.patch.object(coinlens_app, "insert_scan", return_value={"id": "scan-1", "user_id": "user-123"}):
            response = self.client.post(
                "/api/identify-coin",
                json={"front_image": JPEG_BASE64, "source": "camera"},
                headers={"Authorization": f"Bearer {token}"},
            )
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["meta"]["mock"])


if __name__ == "__main__":
    unittest.main()
