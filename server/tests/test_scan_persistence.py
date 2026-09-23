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
import supabase_admin


JPEG_BASE64 = base64.b64encode(b"\xff\xd8\xff\xe0coinlens-test-image").decode("ascii")
TEST_SUPABASE_URL = "https://test.supabase.co"
TEST_ISSUER = f"{TEST_SUPABASE_URL}/auth/v1"
TOKEN_USER_ID = "user-123"

SUCCESSFUL_IDENTIFICATION = {
    "coin_name": "1946 United States Lincoln Wheat Cent",
    "country": "United States",
    "denomination": "One Cent",
    "year": "1946",
    "mint_mark": None,
    "estimated_grade": "VF-30",
    "identifiable": True,
    "confidence": 94,
}

# A completed valuation returned by the pipeline.
SUCCESSFUL_RESULT = {
    "identification": dict(SUCCESSFUL_IDENTIFICATION),
    "valuation": {"status": "available", "estimated_value": 12.50, "currency": "USD", "source": "Numista"},
    "numista": None,
    "pcgs": None,
    "summary": "A coin.",
}

UNIDENTIFIABLE_RESULT = {
    "identification": {"identifiable": False, "coin_name": "Unidentified coin"},
    "valuation": {"status": "unavailable"},
    "summary": "Could not identify.",
}


def make_test_token(sub=TOKEN_USER_ID, aud="authenticated", issuer=TEST_ISSUER, exp_delta=3600):
    private_key = ec.generate_private_key(ec.SECP256R1())
    now = int(time.time())
    claims = {"sub": sub, "aud": aud, "iss": issuer, "iat": now, "exp": now + exp_delta}
    token = jwt.encode(claims, private_key, algorithm="ES256")
    return token, private_key.public_key()


class ScanPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.client = coinlens_app.app.test_client()
        for name, value in [("check_and_reserve_quota", (None, 19)), ("update_api_usage", None)]:
            patcher = mock.patch.object(coinlens_app, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ["MOCK_MODE", "USE_MOCK_COIN_RESPONSE", "OPENAI_API_KEY"]:
            original = getattr(coinlens_app, name)
            self.addCleanup(lambda n=name, v=original: setattr(coinlens_app, n, v))

        # Force the real (non-mock) identification branch so the persistence
        # path under test actually runs, without spending real API credits -
        # build_coinlens_result itself is mocked per test below.
        coinlens_app.MOCK_MODE = False
        coinlens_app.USE_MOCK_COIN_RESPONSE = False
        coinlens_app.OPENAI_API_KEY = "test-key"

        self._original_supabase_url = coinlens_auth.SUPABASE_URL
        coinlens_auth.SUPABASE_URL = TEST_SUPABASE_URL

        token, public_key = make_test_token()
        self.token = token
        self.auth_headers = {"Authorization": f"Bearer {token}"}

        self._signing_key_patcher = mock.patch.object(coinlens_auth, "_get_signing_key", return_value=public_key)
        self._signing_key_patcher.start()
        self.addCleanup(self._signing_key_patcher.stop)
        self.addCleanup(lambda: setattr(coinlens_auth, "SUPABASE_URL", self._original_supabase_url))

    def post_identify(self, payload, headers=None):
        return self.client.post("/api/identify-coin", json=payload, headers=headers)

    def test_requires_authentication(self):
        response = self.post_identify({"front_image": JPEG_BASE64, "source": "camera"})
        body = response.get_json()

        self.assertEqual(response.status_code, 401)
        self.assertEqual(body["error"]["code"], "auth_missing")

    def test_valid_request_persists_scan_under_token_user_id(self):
        with mock.patch.object(coinlens_app, "build_coinlens_result", return_value=dict(SUCCESSFUL_RESULT)), \
             mock.patch.object(coinlens_app, "insert_scan", return_value={"id": "row-1"}) as insert_scan:
            response = self.post_identify(
                {"front_image": JPEG_BASE64, "source": "camera"}, headers=self.auth_headers
            )

        self.assertEqual(response.status_code, 200)
        insert_scan.assert_called_once()
        self.assertEqual(insert_scan.call_args.args[0]["user_id"], TOKEN_USER_ID)

    def test_spoofed_body_user_id_is_ignored(self):
        with mock.patch.object(coinlens_app, "build_coinlens_result", return_value=dict(SUCCESSFUL_RESULT)), \
             mock.patch.object(coinlens_app, "insert_scan", return_value={"id": "row-1"}) as insert_scan:
            response = self.post_identify(
                {"front_image": JPEG_BASE64, "source": "camera", "user_id": "attacker-id"},
                headers=self.auth_headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(insert_scan.call_args.args[0]["user_id"], TOKEN_USER_ID)
        self.assertNotEqual(insert_scan.call_args.args[0]["user_id"], "attacker-id")

    def test_spoofed_query_user_id_is_ignored(self):
        with mock.patch.object(coinlens_app, "build_coinlens_result", return_value=dict(SUCCESSFUL_RESULT)), \
             mock.patch.object(coinlens_app, "insert_scan", return_value={"id": "row-1"}) as insert_scan:
            response = self.client.post(
                "/api/identify-coin?user_id=attacker-id",
                json={"front_image": JPEG_BASE64, "source": "camera"},
                headers=self.auth_headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(insert_scan.call_args.args[0]["user_id"], TOKEN_USER_ID)

    def test_successful_identification_calls_insert_scan(self):
        with mock.patch.object(coinlens_app, "build_coinlens_result", return_value=dict(SUCCESSFUL_RESULT)), \
             mock.patch.object(coinlens_app, "insert_scan", return_value={"id": "row-1"}) as insert_scan:
            response = self.post_identify(
                {"front_image": JPEG_BASE64, "source": "camera"}, headers=self.auth_headers
            )

        self.assertEqual(response.status_code, 200)
        insert_scan.assert_called_once()

    def test_available_valuation_is_persisted(self):
        with mock.patch.object(coinlens_app, "build_coinlens_result", return_value=dict(SUCCESSFUL_RESULT)), \
             mock.patch.object(coinlens_app, "insert_scan", return_value={"id": "row-1"}) as insert_scan:
            self.post_identify({"front_image": JPEG_BASE64, "source": "camera"}, headers=self.auth_headers)

        self.assertEqual(insert_scan.call_args.args[0]["estimated_value"], 12.50)

    def test_unidentifiable_result_does_not_insert_scan(self):
        with mock.patch.object(coinlens_app, "build_coinlens_result", return_value=dict(UNIDENTIFIABLE_RESULT)), \
             mock.patch.object(coinlens_app, "insert_scan") as insert_scan:
            response = self.post_identify(
                {"front_image": JPEG_BASE64, "source": "camera"}, headers=self.auth_headers
            )

        self.assertEqual(response.status_code, 422)
        insert_scan.assert_not_called()

    def test_upstream_identification_failure_does_not_insert_scan(self):
        error = coinlens_app.CoinLensError("upstream_failure", "AI provider request failed.", 502)
        with mock.patch.object(coinlens_app, "build_coinlens_result", side_effect=error), \
             mock.patch.object(coinlens_app, "insert_scan") as insert_scan:
            response = self.post_identify(
                {"front_image": JPEG_BASE64, "source": "camera"}, headers=self.auth_headers
            )

        self.assertEqual(response.status_code, 502)
        insert_scan.assert_not_called()

    def test_invalid_source_is_rejected(self):
        response = self.post_identify(
            {"front_image": JPEG_BASE64, "source": "screenshot"}, headers=self.auth_headers
        )
        body = response.get_json()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(body["error"]["code"], "invalid_source")

    def test_missing_source_is_rejected(self):
        response = self.post_identify({"front_image": JPEG_BASE64}, headers=self.auth_headers)
        body = response.get_json()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(body["error"]["code"], "invalid_source")

    def test_supabase_admin_failure_returns_honest_server_error(self):
        with mock.patch.object(coinlens_app, "build_coinlens_result", return_value=dict(SUCCESSFUL_RESULT)), \
             mock.patch.object(
                 coinlens_app, "insert_scan", side_effect=supabase_admin.SupabaseAdminError("boom")
             ):
            response = self.post_identify(
                {"front_image": JPEG_BASE64, "source": "camera"}, headers=self.auth_headers
            )
        body = response.get_json()

        self.assertEqual(response.status_code, 500)
        self.assertEqual(body["error"]["code"], "scan_insert_failed")
        self.assertNotIn("boom", body["error"]["message"])

    def test_mock_mode_persists_scan(self):
        coinlens_app.MOCK_MODE = True
        with mock.patch.object(coinlens_app, "insert_scan", return_value={"id": "mock-row"}) as insert_scan:
            response = self.post_identify(
                {"front_image": JPEG_BASE64, "source": "camera"}, headers=self.auth_headers
            )

        self.assertEqual(response.status_code, 200)
        insert_scan.assert_called_once()


if __name__ == "__main__":
    unittest.main()
