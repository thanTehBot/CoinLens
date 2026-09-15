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
from mock_openai import MOCK_MARKER


JPEG_BASE64 = base64.b64encode(b"\xff\xd8\xff\xe0coinlens-test-image").decode("ascii")
TEST_SUPABASE_URL = "https://test.supabase.co"
TEST_ISSUER = f"{TEST_SUPABASE_URL}/auth/v1"


def make_test_token(sub="user-123", aud="authenticated", issuer=TEST_ISSUER, exp_delta=3600):
    private_key = ec.generate_private_key(ec.SECP256R1())
    now = int(time.time())
    claims = {"sub": sub, "aud": aud, "iss": issuer, "iat": now, "exp": now + exp_delta}
    token = jwt.encode(claims, private_key, algorithm="ES256")
    return token, private_key.public_key()


class CoinLensApiTests(unittest.TestCase):
    def setUp(self):
        self.client = coinlens_app.app.test_client()
        coinlens_app.MOCK_MODE = False
        coinlens_app.USE_MOCK_COIN_RESPONSE = False
        coinlens_app.OPENAI_API_KEY = ""
        coinlens_app.NUMISTA_API_KEY = ""
        coinlens_app.PCGS_BEARER_TOKEN = ""
        coinlens_app.SHEETDB_URL = ""

    def enable_mock(self):
        coinlens_app.MOCK_MODE = True
        coinlens_app.USE_MOCK_COIN_RESPONSE = False

        self._original_supabase_url = coinlens_auth.SUPABASE_URL
        coinlens_auth.SUPABASE_URL = TEST_SUPABASE_URL
        token, public_key = make_test_token()
        self.auth_headers = {"Authorization": f"Bearer {token}"}
        self._signing_key_patcher = mock.patch.object(coinlens_auth, "_get_signing_key", return_value=public_key)
        self._signing_key_patcher.start()
        self.addCleanup(self._signing_key_patcher.stop)
        self.addCleanup(lambda: setattr(coinlens_auth, "SUPABASE_URL", self._original_supabase_url))

    def test_health(self):
        self.enable_mock()
        response = self.client.get("/api/health")
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["ok"], True)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["mock_mode"], True)
        self.assertEqual(body["has_openai_key"], False)
        self.assertEqual(body["has_numista_key"], False)
        self.assertEqual(body["has_pcgs_token"], False)
        self.assertEqual(body["has_sheetdb"], False)

    def test_identify_coin_missing_image(self):
        response = self.client.post("/api/identify-coin", json={}, headers=self.auth_headers)
        body = response.get_json()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(body["error"]["code"], "missing_image")

    def test_identify_coin_server_mock_mode(self):
        self.enable_mock()

        response = self.client.post(
            "/api/identify-coin", json={"front_image": JPEG_BASE64, "source": "camera"}, headers=self.auth_headers
        )
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["meta"]["mock"])
        self.assertEqual(body["identification"]["year"], "1946")
        self.assertEqual(body["identification"]["coin_name"], "1946 United States Lincoln Wheat Cent")
        self.assertEqual(body["identification"]["estimated_grade"], "VF-30")
        self.assertEqual(body["valuation"]["status"], "available")
        self.assertEqual(body["valuation"]["estimated_value"], 12.34)
        self.assertIn(MOCK_MARKER, body["summary"])

    def test_identify_coin_missing_openai_key_uses_mock_response(self):
        response = self.client.post("/api/identify-coin", json={"front_image": JPEG_BASE64})
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["meta"]["mock"])
        self.assertEqual(body["identification"]["year"], "1946")
        self.assertNotIn("error", body)

    def test_identify_coin_single_image_request(self):
        self.enable_mock()

        response = self.client.post(
            "/api/identify-coin", json={"front_image": JPEG_BASE64, "source": "camera"}, headers=self.auth_headers
        )
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["meta"]["front_image_received"])
        self.assertFalse(body["meta"]["back_image_received"])

    def test_identify_coin_two_image_request(self):
        self.enable_mock()

        response = self.client.post(
            "/api/identify-coin",
            json={"front_image": JPEG_BASE64, "back_image": JPEG_BASE64, "source": "gallery"},
            headers=self.auth_headers,
        )
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["meta"]["front_image_received"])
        self.assertTrue(body["meta"]["back_image_received"])

    def test_generate_ebay_listing_mock(self):
        self.enable_mock()

        response = self.client.post("/api/generate-ebay-listing", json={})
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIn("1946 Lincoln Wheat Cent", body["title"])
        self.assertIn(MOCK_MARKER, body["subtitle"])
        self.assertIsInstance(body["item_specifics"], list)

    def test_proxy_routes_return_mock_payloads(self):
        self.enable_mock()

        openai = self.client.post("/api/openai/chat", json={"messages": []}).get_json()
        numista = self.client.get("/api/numista-specs?q=cent").get_json()
        pcgs = self.client.get("/api/pcgs-value/2731").get_json()
        log_scan = self.client.post("/api/log-scan", json={}).get_json()
        scans = self.client.get("/api/scans").get_json()

        self.assertIn(MOCK_MARKER, openai["choices"][0]["message"]["content"])
        self.assertEqual(numista["items"][0]["title"], "Lincoln Cent - Wheat reverse")
        self.assertEqual(pcgs["price"], 12.34)
        self.assertEqual(log_scan, {"success": True, "marker": MOCK_MARKER})
        self.assertEqual(scans[0]["Coin"], "1946 United States Lincoln Wheat Cent")

    def test_successful_response_contract(self):
        self.enable_mock()

        response = self.client.post(
            "/api/identify-coin", json={"front_image": JPEG_BASE64, "source": "camera"}, headers=self.auth_headers
        )
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIn("identification", body)
        self.assertIn("valuation", body)
        self.assertIn("numista", body)
        self.assertIn("pcgs", body)
        self.assertIn("summary", body)
        self.assertIn("marker", body)

    def test_simulated_upstream_failure(self):
        coinlens_app.OPENAI_API_KEY = "test-key"
        error = coinlens_app.CoinLensError("upstream_failure", "AI provider request failed.", 502)
        with mock.patch.object(coinlens_app, "identify_with_ai", side_effect=error):
            response = self.client.post("/api/identify-coin", json={"front_image": JPEG_BASE64}, headers=self.auth_headers)
        body = response.get_json()

        self.assertEqual(response.status_code, 502)
        self.assertEqual(body["error"]["code"], "upstream_failure")

    def test_malformed_ai_response(self):
        coinlens_app.OPENAI_API_KEY = "test-key"
        calls = iter(["visual description", "this is not json"])

        with mock.patch.object(coinlens_app, "openai_chat_content", side_effect=lambda *args, **kwargs: next(calls)):
            response = self.client.post("/api/identify-coin", json={"front_image": JPEG_BASE64}, headers=self.auth_headers)
        body = response.get_json()

        self.assertEqual(response.status_code, 502)
        self.assertEqual(body["error"]["code"], "malformed_ai_response")


if __name__ == "__main__":
    unittest.main()
