import base64
import json
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


def grounded_observations(front_text="", back_text="", numerals=(), country_text="", denomination_text="", year_text="",
                          shape="round", side_count=None, bimetallic="no", color="copper-colored"):
    """A model "observations" block where country/denomination/year are all
    backed by legible text - what the evidence gate requires to accept an
    "identified" result."""
    return {
        "observed_text_front": front_text,
        "observed_text_back": back_text,
        "observed_numerals": list(numerals),
        "observed_shape": shape,
        "observed_side_count": side_count,
        "observed_color_or_material": color,
        "observed_bimetallic": bimetallic,
        "country_evidence": {"basis": "read_on_coin", "visible_text": country_text},
        "denomination_evidence": {"basis": "read_on_coin", "visible_text": denomination_text},
        "year_evidence": {"basis": "read_on_coin", "visible_text": year_text},
    }


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
        coinlens_app.DAILY_SCAN_LIMIT = 20
        coinlens_app.MAX_IMAGE_BYTES = 8 * 1024 * 1024
        coinlens_app.ENABLE_EBAY_LISTING = False

    def enable_mock(self):
        coinlens_app.MOCK_MODE = True
        coinlens_app.USE_MOCK_COIN_RESPONSE = False
        self._authenticate()

    def _authenticate(self):
        """Sets up a verifiable JWT without depending on MOCK_MODE, so tests
        that exercise the real (non-mock) upstream-failure paths can still
        authenticate."""
        self._original_supabase_url = coinlens_auth.SUPABASE_URL
        coinlens_auth.SUPABASE_URL = TEST_SUPABASE_URL
        token, public_key = make_test_token()
        self.auth_headers = {"Authorization": f"Bearer {token}"}
        self._signing_key_patcher = mock.patch.object(coinlens_auth, "_get_signing_key", return_value=public_key)
        self._signing_key_patcher.start()
        self.addCleanup(self._signing_key_patcher.stop)
        self.addCleanup(lambda: setattr(coinlens_auth, "SUPABASE_URL", self._original_supabase_url))

    def mock_persisted_scan(self, **overrides):
        """Unit tests must never touch the real Supabase project even though
        server/.env has real credentials loaded - patch the insert instead."""
        row = {
            "id": "11111111-1111-1111-1111-111111111111",
            "user_id": "user-123",
            "coin_name": "1946 United States Lincoln Wheat Cent",
            "source": "camera",
            **overrides,
        }
        patcher = mock.patch.object(coinlens_app, "insert_scan", return_value=row)
        patcher.start()
        self.addCleanup(patcher.stop)
        return row

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
        self._authenticate()
        response = self.client.post("/api/identify-coin", json={"source": "camera"}, headers=self.auth_headers)
        body = response.get_json()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(body["error"]["code"], "missing_image")

    def test_identify_coin_missing_source(self):
        self._authenticate()
        response = self.client.post("/api/identify-coin", json={"front_image": JPEG_BASE64}, headers=self.auth_headers)
        body = response.get_json()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(body["error"]["code"], "invalid_source")

    def test_identify_coin_server_mock_mode(self):
        self.enable_mock()
        self.mock_persisted_scan()

        response = self.client.post(
            "/api/identify-coin",
            json={"front_image": JPEG_BASE64, "source": "camera"},
            headers=self.auth_headers,
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
        self.assertEqual(body["scan"]["id"], "11111111-1111-1111-1111-111111111111")

    def test_identify_coin_missing_openai_key_uses_mock_response(self):
        self._authenticate()
        self.mock_persisted_scan()

        response = self.client.post(
            "/api/identify-coin",
            json={"front_image": JPEG_BASE64, "source": "gallery"},
            headers=self.auth_headers,
        )
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["meta"]["mock"])
        self.assertEqual(body["identification"]["year"], "1946")
        self.assertNotIn("error", body)

    def test_identify_coin_single_image_request(self):
        self.enable_mock()
        self.mock_persisted_scan()

        response = self.client.post(
            "/api/identify-coin",
            json={"front_image": JPEG_BASE64, "source": "camera"},
            headers=self.auth_headers,
        )
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["meta"]["front_image_received"])
        self.assertFalse(body["meta"]["back_image_received"])

    def test_identify_coin_two_image_request(self):
        self.enable_mock()
        self.mock_persisted_scan()

        response = self.client.post(
            "/api/identify-coin",
            json={"front_image": JPEG_BASE64, "back_image": JPEG_BASE64, "source": "camera"},
            headers=self.auth_headers,
        )
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["meta"]["front_image_received"])
        self.assertTrue(body["meta"]["back_image_received"])

    def test_identify_coin_persists_scan_with_derived_fields(self):
        self.enable_mock()
        with mock.patch.object(coinlens_app, "insert_scan") as mock_insert:
            mock_insert.return_value = {"id": "scan-1", "user_id": "user-123"}
            response = self.client.post(
                "/api/identify-coin",
                json={"front_image": JPEG_BASE64, "source": "gallery"},
                headers=self.auth_headers,
            )

        self.assertEqual(response.status_code, 200)
        mock_insert.assert_called_once()
        payload = mock_insert.call_args[0][0]
        self.assertEqual(payload["user_id"], "user-123")
        self.assertEqual(payload["source"], "gallery")
        self.assertEqual(payload["year"], 1946)
        self.assertEqual(payload["denom_canonical"], "wheat-penny")
        self.assertFalse(payload["is_foreign"])
        self.assertIn("local_date", payload)
        self.assertIn("local_hour", payload)

    def test_identify_coin_uncertain_does_not_persist(self):
        self._authenticate()
        coinlens_app.OPENAI_API_KEY = "test-key"
        uncertain = {
            "coin_name": "Unidentified coin", "country": "Unknown", "denomination": "Unknown",
            "year": "Unknown", "mint_mark": None, "estimated_grade": "Unknown", "description": "",
            "mint_errors": [], "varieties": None, "error_premium": False, "special_notes": "",
            "status": "uncertain", "identifiable": False,
            "unidentifiable_reason": "Photo is too blurry.", "confidence": 10, "alternatives": [],
        }
        with mock.patch.object(coinlens_app, "identify_coin_with_ai", return_value=uncertain), \
             mock.patch.object(coinlens_app, "insert_api_usage", return_value={"id": "usage-1"}), \
             mock.patch.object(coinlens_app, "count_api_usage_since", return_value=0), \
             mock.patch.object(coinlens_app, "update_api_usage") as mock_update, \
             mock.patch.object(coinlens_app, "insert_scan") as mock_insert:
            response = self.client.post(
                "/api/identify-coin",
                json={"front_image": JPEG_BASE64, "source": "camera"},
                headers=self.auth_headers,
            )
        body = response.get_json()

        self.assertEqual(response.status_code, 422)
        self.assertEqual(body["identification"]["identifiable"], False)
        mock_insert.assert_not_called()
        mock_update.assert_called_once_with("usage-1", {"status": "uncertain"})

    def test_identify_coin_quota_exceeded_returns_429(self):
        self._authenticate()
        coinlens_app.OPENAI_API_KEY = "test-key"
        coinlens_app.DAILY_SCAN_LIMIT = 5
        with mock.patch.object(coinlens_app, "count_api_usage_since", return_value=5), \
             mock.patch.object(coinlens_app, "identify_coin_with_ai") as mock_identify:
            response = self.client.post(
                "/api/identify-coin",
                json={"front_image": JPEG_BASE64, "source": "camera"},
                headers=self.auth_headers,
            )
        body = response.get_json()

        self.assertEqual(response.status_code, 429)
        self.assertEqual(body["error"]["code"], "quota_exceeded")
        mock_identify.assert_not_called()

    def test_identify_coin_oversized_image_rejected(self):
        self._authenticate()
        coinlens_app.MAX_IMAGE_BYTES = 10
        response = self.client.post(
            "/api/identify-coin",
            json={"front_image": JPEG_BASE64, "source": "camera"},
            headers=self.auth_headers,
        )
        body = response.get_json()

        self.assertEqual(response.status_code, 413)
        self.assertEqual(body["error"]["code"], "image_too_large")

    def test_generate_ebay_listing_mock(self):
        self.enable_mock()
        # Underlying implementation is preserved and still testable when the
        # V1 feature flag is explicitly turned on.
        coinlens_app.ENABLE_EBAY_LISTING = True

        response = self.client.post("/api/generate-ebay-listing", json={}, headers=self.auth_headers)
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIn("1946 Lincoln Wheat Cent", body["title"])
        self.assertIn(MOCK_MARKER, body["subtitle"])
        self.assertIsInstance(body["item_specifics"], list)

    def test_generate_ebay_listing_disabled_by_default(self):
        # setUp already leaves ENABLE_EBAY_LISTING at its false default.
        self._authenticate()

        response = self.client.post("/api/generate-ebay-listing", json={}, headers=self.auth_headers)
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body, {
            "feature_disabled": True,
            "feature": "ebay_listing",
            "message": "eBay listing generation is disabled in this version.",
        })

    def test_generate_ebay_listing_disabled_never_calls_openai(self):
        self._authenticate()
        coinlens_app.OPENAI_API_KEY = "test-key"
        coinlens_app.ENABLE_EBAY_LISTING = False

        with mock.patch.object(coinlens_app.requests, "post", side_effect=AssertionError("should not call OpenAI")):
            response = self.client.post(
                "/api/generate-ebay-listing",
                json={"identification": {"coin_name": "Anything"}},
                headers=self.auth_headers,
            )
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["feature_disabled"])

    def test_proxy_routes_return_mock_payloads(self):
        self.enable_mock()

        numista = self.client.get("/api/numista-specs?q=cent").get_json()
        pcgs = self.client.get("/api/pcgs-value/2731").get_json()
        log_scan = self.client.post("/api/log-scan", json={}).get_json()
        scans = self.client.get("/api/scans").get_json()

        self.assertEqual(numista["items"][0]["title"], "Lincoln Cent - Wheat reverse")
        self.assertEqual(pcgs["price"], 12.34)
        self.assertEqual(log_scan, {"success": True, "marker": MOCK_MARKER})
        self.assertEqual(scans[0]["Coin"], "1946 United States Lincoln Wheat Cent")

    def test_openai_chat_route_removed(self):
        self._authenticate()
        response = self.client.post("/api/openai/chat", json={"messages": []}, headers=self.auth_headers)
        body = response.get_json()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(body["error"]["code"], "not_found")
        self.assertNotIn("choices", body)

    def test_unknown_route_returns_structured_404_not_500(self):
        # A stray/mistyped URL hitting the server (e.g. someone navigating to
        # /identify-coin instead of the real /api/identify-coin) must read as
        # a clean 404 in logs and to any caller, not a scary 500 that looks
        # like a server crash.
        response = self.client.get("/identify-coin")
        body = response.get_json()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(body["error"]["code"], "not_found")

    def test_wrong_method_returns_structured_405(self):
        # /api/identify-coin only accepts POST.
        response = self.client.get("/api/identify-coin")
        body = response.get_json()

        self.assertEqual(response.status_code, 405)
        self.assertEqual(body["error"]["code"], "method_not_allowed")

    def test_oversized_upload_still_returns_413_not_generic_http_exception(self):
        # The more specific @app.errorhandler(413) must still win over the
        # new blanket HTTPException handler for this exact case.
        self._authenticate()
        coinlens_app.MAX_IMAGE_BYTES = 10
        response = self.client.post(
            "/api/identify-coin",
            json={"front_image": JPEG_BASE64, "source": "camera"},
            headers=self.auth_headers,
        )
        body = response.get_json()

        self.assertEqual(response.status_code, 413)
        self.assertEqual(body["error"]["code"], "image_too_large")

    def test_unexpected_server_error_still_returns_500(self):
        # Real bugs must still surface as 500, not get miscategorized by the
        # new HTTPException handler (which only catches routing-level cases).
        self.enable_mock()
        with mock.patch.object(coinlens_app, "build_coinlens_result", side_effect=RuntimeError("boom")):
            response = self.client.post(
                "/api/identify-coin",
                json={"front_image": JPEG_BASE64, "source": "camera"},
                headers=self.auth_headers,
            )
        body = response.get_json()

        self.assertEqual(response.status_code, 500)
        self.assertEqual(body["error"]["code"], "server_error")

    def test_successful_response_contract(self):
        self.enable_mock()
        self.mock_persisted_scan()

        response = self.client.post(
            "/api/identify-coin",
            json={"front_image": JPEG_BASE64, "source": "camera"},
            headers=self.auth_headers,
        )
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIn("identification", body)
        self.assertIn("valuation", body)
        self.assertIn("numista", body)
        self.assertIn("pcgs", body)
        self.assertIn("summary", body)
        self.assertIn("marker", body)
        self.assertIn("scan", body)

    def test_simulated_upstream_failure(self):
        self._authenticate()
        coinlens_app.OPENAI_API_KEY = "test-key"
        error = coinlens_app.CoinLensError("upstream_failure", "AI provider request failed.", 502)
        with mock.patch.object(coinlens_app, "identify_coin_with_ai", side_effect=error), \
             mock.patch.object(coinlens_app, "count_api_usage_since", return_value=0), \
             mock.patch.object(coinlens_app, "insert_api_usage", return_value={"id": "usage-1"}), \
             mock.patch.object(coinlens_app, "update_api_usage") as mock_update:
            response = self.client.post(
                "/api/identify-coin",
                json={"front_image": JPEG_BASE64, "source": "camera"},
                headers=self.auth_headers,
            )
        body = response.get_json()

        self.assertEqual(response.status_code, 502)
        self.assertEqual(body["error"]["code"], "upstream_failure")
        mock_update.assert_called_once_with("usage-1", {"status": "error"})

    def test_malformed_ai_response(self):
        self._authenticate()
        coinlens_app.OPENAI_API_KEY = "test-key"

        with mock.patch.object(coinlens_app.requests, "post") as mock_post, \
             mock.patch.object(coinlens_app, "count_api_usage_since", return_value=0), \
             mock.patch.object(coinlens_app, "insert_api_usage", return_value={"id": "usage-1"}), \
             mock.patch.object(coinlens_app, "update_api_usage"):
            mock_post.return_value = mock.Mock(
                ok=True,
                status_code=200,
                json=lambda: {"output_text": "this is not json"},
            )
            response = self.client.post(
                "/api/identify-coin",
                json={"front_image": JPEG_BASE64, "source": "camera"},
                headers=self.auth_headers,
            )
        body = response.get_json()

        self.assertEqual(response.status_code, 502)
        self.assertEqual(body["error"]["code"], "malformed_ai_response")

    # -- OpenAI rate limits: a real 429 from OpenAI itself (not our own
    # quota_exceeded), and logging real token usage so a future rate-limit
    # report can be diagnosed from Render logs instead of guessing. --------

    def test_identify_coin_openai_rate_limit_returns_429(self):
        self._authenticate()
        coinlens_app.OPENAI_API_KEY = "test-key"

        with mock.patch.object(coinlens_app.requests, "post") as mock_post, \
             mock.patch.object(coinlens_app, "count_api_usage_since", return_value=0), \
             mock.patch.object(coinlens_app, "insert_api_usage", return_value={"id": "usage-1"}), \
             mock.patch.object(coinlens_app, "update_api_usage") as mock_update:
            mock_post.return_value = mock.Mock(
                ok=False,
                status_code=429,
                text='{"error": {"message": "Rate limit reached for requests"}}',
                headers={},
                json=lambda: {"error": {"message": "Rate limit reached for requests"}},
            )
            response = self.client.post(
                "/api/identify-coin",
                json={"front_image": JPEG_BASE64, "source": "camera"},
                headers=self.auth_headers,
            )
        body = response.get_json()

        self.assertEqual(response.status_code, 429)
        self.assertEqual(body["error"]["code"], "rate_limit")
        mock_update.assert_called_once_with("usage-1", {"status": "error"})

    def test_identify_coin_logs_openai_429_headers_and_body(self):
        """The diagnostic log must capture status, the standard rate-limit
        headers (only the ones actually present), and the body - without
        changing the existing 429 -> rate_limit contract."""
        self._authenticate()
        coinlens_app.OPENAI_API_KEY = "test-key"

        rate_limit_headers = {
            "x-request-id": "req_abc123",
            "x-ratelimit-limit-requests": "3",
            "x-ratelimit-remaining-requests": "0",
            "x-ratelimit-reset-requests": "12.5s",
            "x-ratelimit-limit-tokens": "10000",
            "x-ratelimit-remaining-tokens": "4416",
            "x-ratelimit-reset-tokens": "1s",
            "retry-after": "13",
        }
        with mock.patch.object(coinlens_app.requests, "post") as mock_post, \
             mock.patch.object(coinlens_app, "count_api_usage_since", return_value=0), \
             mock.patch.object(coinlens_app, "insert_api_usage", return_value={"id": "usage-1"}), \
             mock.patch.object(coinlens_app, "update_api_usage"):
            mock_post.return_value = mock.Mock(
                ok=False,
                status_code=429,
                text='{"error": {"message": "Rate limit reached for requests"}}',
                headers=rate_limit_headers,
                json=lambda: {"error": {"message": "Rate limit reached for requests"}},
            )
            with self.assertLogs(coinlens_app.app.logger, level="WARNING") as logs:
                response = self.client.post(
                    "/api/identify-coin",
                    json={"front_image": JPEG_BASE64, "source": "camera"},
                    headers=self.auth_headers,
                )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.get_json()["error"]["code"], "rate_limit")

        error_log_lines = [line for line in logs.output if "OpenAI error response" in line]
        self.assertEqual(len(error_log_lines), 1)
        log_line = error_log_lines[0]
        self.assertIn("http_status=429", log_line)
        self.assertIn("Rate limit reached for requests", log_line)
        for header_name, header_value in rate_limit_headers.items():
            self.assertIn(header_name, log_line)
            self.assertIn(header_value, log_line)

    def test_identify_coin_openai_error_logging_omits_absent_headers(self):
        """Only headers OpenAI actually sent should appear in the log -
        never a synthesized/None entry for a header that wasn't present."""
        self._authenticate()
        coinlens_app.OPENAI_API_KEY = "test-key"

        with mock.patch.object(coinlens_app.requests, "post") as mock_post, \
             mock.patch.object(coinlens_app, "count_api_usage_since", return_value=0), \
             mock.patch.object(coinlens_app, "insert_api_usage", return_value={"id": "usage-1"}), \
             mock.patch.object(coinlens_app, "update_api_usage"):
            mock_post.return_value = mock.Mock(
                ok=False,
                status_code=429,
                text='{"error": {"message": "Rate limit reached"}}',
                headers={"retry-after": "5"},
                json=lambda: {"error": {"message": "Rate limit reached"}},
            )
            with self.assertLogs(coinlens_app.app.logger, level="WARNING") as logs:
                self.client.post(
                    "/api/identify-coin",
                    json={"front_image": JPEG_BASE64, "source": "camera"},
                    headers=self.auth_headers,
                )

        log_line = next(line for line in logs.output if "OpenAI error response" in line)
        self.assertIn("retry-after", log_line)
        self.assertNotIn("x-ratelimit-limit-requests", log_line)
        self.assertNotIn("x-request-id", log_line)

    def test_identify_coin_openai_error_logging_never_leaks_secrets_or_images(self):
        """The diagnostic log is built only from the OpenAI response object -
        assert the API key, the Authorization header value, and a
        base64-image-shaped payload never appear in the log line, and that
        a long base64-looking run in the body itself gets redacted."""
        self._authenticate()
        coinlens_app.OPENAI_API_KEY = "super-secret-openai-key"
        fake_base64_blob = "A" * 500

        with mock.patch.object(coinlens_app.requests, "post") as mock_post, \
             mock.patch.object(coinlens_app, "count_api_usage_since", return_value=0), \
             mock.patch.object(coinlens_app, "insert_api_usage", return_value={"id": "usage-1"}), \
             mock.patch.object(coinlens_app, "update_api_usage"):
            mock_post.return_value = mock.Mock(
                ok=False,
                status_code=400,
                text=f'{{"error": {{"message": "bad request", "echo": "{fake_base64_blob}"}}}}',
                headers={},
                json=lambda: {"error": {"message": "bad request"}},
            )
            with self.assertLogs(coinlens_app.app.logger, level="WARNING") as logs:
                self.client.post(
                    "/api/identify-coin",
                    json={"front_image": JPEG_BASE64, "source": "camera"},
                    headers=self.auth_headers,
                )

        log_line = next(line for line in logs.output if "OpenAI error response" in line)
        self.assertNotIn("super-secret-openai-key", log_line)
        self.assertNotIn(f"Bearer {coinlens_app.OPENAI_API_KEY}", log_line)
        self.assertNotIn(fake_base64_blob, log_line)
        self.assertIn("<redacted-base64>", log_line)

    # -- retry_after_seconds: propagating OpenAI's real retry-after header
    # to Expo so the UI can offer an accurate wait instead of a hardcoded
    # "30 seconds" regardless of how long OpenAI actually says to wait. ---

    def _post_rate_limited(self, retry_after_header, message="Rate limit reached for gpt-5.6-luna on tokens per min."):
        headers = {} if retry_after_header is None else {"retry-after": retry_after_header}
        with mock.patch.object(coinlens_app.requests, "post") as mock_post, \
             mock.patch.object(coinlens_app, "count_api_usage_since", return_value=0), \
             mock.patch.object(coinlens_app, "insert_api_usage", return_value={"id": "usage-1"}), \
             mock.patch.object(coinlens_app, "update_api_usage"):
            mock_post.return_value = mock.Mock(
                ok=False,
                status_code=429,
                text='{"error": {"message": "%s"}}' % message,
                headers=headers,
                json=lambda: {"error": {"message": message}},
            )
            return self.client.post(
                "/api/identify-coin",
                json={"front_image": JPEG_BASE64, "source": "camera"},
                headers=self.auth_headers,
            )

    def test_retry_after_30_seconds_is_propagated(self):
        self._authenticate()
        coinlens_app.OPENAI_API_KEY = "test-key"
        response = self._post_rate_limited("30")
        body = response.get_json()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(body["error"]["code"], "rate_limit")
        self.assertEqual(body["error"]["retry_after_seconds"], 30)

    def test_retry_after_300_seconds_is_propagated(self):
        self._authenticate()
        coinlens_app.OPENAI_API_KEY = "test-key"
        response = self._post_rate_limited("300")
        body = response.get_json()
        self.assertEqual(body["error"]["retry_after_seconds"], 300)

    def test_retry_after_11042_seconds_is_propagated(self):
        """The exact real-world example that prompted this change: a
        multi-hour retry window, not the old hardcoded '30 seconds'."""
        self._authenticate()
        coinlens_app.OPENAI_API_KEY = "test-key"
        response = self._post_rate_limited("11042")
        body = response.get_json()
        self.assertEqual(body["error"]["retry_after_seconds"], 11042)

    def test_missing_retry_after_header_omits_the_field(self):
        self._authenticate()
        coinlens_app.OPENAI_API_KEY = "test-key"
        response = self._post_rate_limited(None)
        body = response.get_json()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(body["error"]["code"], "rate_limit")
        self.assertNotIn("retry_after_seconds", body["error"])

    def test_malformed_retry_after_header_omits_the_field_without_crashing(self):
        self._authenticate()
        coinlens_app.OPENAI_API_KEY = "test-key"
        for malformed_value in ("soon", "", "-5", "3.5", "Wed, 21 Oct 2026 07:28:00 GMT"):
            with self.subTest(malformed_value=malformed_value):
                response = self._post_rate_limited(malformed_value)
                body = response.get_json()
                self.assertEqual(response.status_code, 429)
                self.assertEqual(body["error"]["code"], "rate_limit")
                self.assertNotIn("retry_after_seconds", body["error"])

    def test_rate_limit_response_never_exposes_raw_provider_details(self):
        """Org/project id, x-request-id, raw body, token counts, and auth
        info must never reach Expo - those stay in server-side logs only."""
        self._authenticate()
        coinlens_app.OPENAI_API_KEY = "test-key"
        with mock.patch.object(coinlens_app.requests, "post") as mock_post, \
             mock.patch.object(coinlens_app, "count_api_usage_since", return_value=0), \
             mock.patch.object(coinlens_app, "insert_api_usage", return_value={"id": "usage-1"}), \
             mock.patch.object(coinlens_app, "update_api_usage"):
            mock_post.return_value = mock.Mock(
                ok=False,
                status_code=429,
                text=(
                    '{"error": {"message": "Rate limit reached for gpt-5.6-luna on tokens per min. '
                    'Limit 100000, Used 96341, Requested 4085."}}'
                ),
                headers={
                    "retry-after": "11042",
                    "x-request-id": "req_super_secret_id",
                    "x-ratelimit-limit-tokens": "100000",
                    "x-ratelimit-remaining-tokens": "0",
                    "openai-organization": "org-secretorgid",
                    "openai-project": "proj-secretprojectid",
                },
                json=lambda: {"error": {"message": "Rate limit reached for gpt-5.6-luna on tokens per min."}},
            )
            response = self.client.post(
                "/api/identify-coin",
                json={"front_image": JPEG_BASE64, "source": "camera"},
                headers=self.auth_headers,
            )
        body = response.get_json()

        self.assertEqual(body["error"], {
            "code": "rate_limit",
            "message": "AI provider rate or quota limit reached.",
            "retry_after_seconds": 11042,
        })
        response_text = response.get_data(as_text=True)
        for leaked in ("req_super_secret_id", "org-secretorgid", "proj-secretprojectid", "96341", "100000", "Bearer test-key"):
            self.assertNotIn(leaked, response_text)

    def test_identify_coin_logs_openai_token_usage_on_success(self):
        self._authenticate()
        coinlens_app.OPENAI_API_KEY = "test-key"
        self.mock_persisted_scan()

        identification = {
            "status": "identified", "coin_name": "2016 Canada 1 Dollar",
            "country": "Canada", "denomination": "1 dollar", "year": "2016",
            "mint_mark": None, "estimated_grade": "AU-50", "confidence": 90,
            "description": "", "mint_errors": [], "varieties": None,
            "error_premium": False, "special_notes": "", "unidentifiable_reason": None,
            "alternatives": [],
            "observations": grounded_observations(
                "ELIZABETH II D G REGINA", "CANADA DOLLAR 2016", ["2016"], "CANADA", "DOLLAR", "2016",
            ),
        }

        with mock.patch.object(coinlens_app.requests, "post") as mock_post, \
             mock.patch.object(coinlens_app, "count_api_usage_since", return_value=0), \
             mock.patch.object(coinlens_app, "insert_api_usage", return_value={"id": "usage-1"}), \
             mock.patch.object(coinlens_app, "update_api_usage"):
            mock_post.return_value = mock.Mock(
                ok=True,
                status_code=200,
                json=lambda: {
                    "output_text": json.dumps(identification),
                    "usage": {"input_tokens": 17321, "output_tokens": 210, "total_tokens": 17531},
                },
            )
            with self.assertLogs(coinlens_app.app.logger, level="INFO") as logs:
                response = self.client.post(
                    "/api/identify-coin",
                    json={"front_image": JPEG_BASE64, "back_image": JPEG_BASE64, "source": "camera"},
                    headers=self.auth_headers,
                )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(
            "OpenAI usage" in message and "input_tokens=17321" in message
            for message in logs.output
        ))

    def test_identify_coin_sends_headroom_for_reasoning_tokens(self):
        """max_output_tokens must leave room for reasoning-capable models to
        spend part of the budget on hidden reasoning before the final JSON -
        this is a regression guard for the 1000-token cap that produced an
        empty response (see the truncation test below)."""
        self._authenticate()
        coinlens_app.OPENAI_API_KEY = "test-key"
        self.mock_persisted_scan()

        identification = {
            "status": "identified", "coin_name": "2016 Canada 1 Dollar",
            "country": "Canada", "denomination": "1 dollar", "year": "2016",
            "mint_mark": None, "estimated_grade": "AU-50", "confidence": 90,
            "description": "", "mint_errors": [], "varieties": None,
            "error_premium": False, "special_notes": "", "unidentifiable_reason": None,
            "alternatives": [],
        }

        with mock.patch.object(coinlens_app.requests, "post") as mock_post, \
             mock.patch.object(coinlens_app, "count_api_usage_since", return_value=0), \
             mock.patch.object(coinlens_app, "insert_api_usage", return_value={"id": "usage-1"}), \
             mock.patch.object(coinlens_app, "update_api_usage"):
            mock_post.return_value = mock.Mock(
                ok=True, status_code=200, json=lambda: {"output_text": json.dumps(identification)},
            )
            self.client.post(
                "/api/identify-coin",
                json={"front_image": JPEG_BASE64, "source": "camera"},
                headers=self.auth_headers,
            )

        sent_payload = mock_post.call_args.kwargs["json"]
        self.assertGreaterEqual(sent_payload["max_output_tokens"], 2000)

    def test_identify_coin_truncated_by_max_output_tokens_is_ai_incomplete_not_identification_failure(self):
        """Reproduces the real production case: output_tokens hit the cap
        exactly, all of it spent on hidden reasoning, so output_text is
        empty. This is a provider processing failure, not a genuine
        "coin not recognized" - must surface as the distinct, retryable
        ai_incomplete code (previously misreported as
        identification_failure, which told the user to retake the photo
        for a problem that was never about the image)."""
        self._authenticate()
        coinlens_app.OPENAI_API_KEY = "test-key"

        with mock.patch.object(coinlens_app.requests, "post") as mock_post, \
             mock.patch.object(coinlens_app, "count_api_usage_since", return_value=0), \
             mock.patch.object(coinlens_app, "insert_api_usage", return_value={"id": "usage-1"}), \
             mock.patch.object(coinlens_app, "update_api_usage") as mock_update:
            mock_post.return_value = mock.Mock(
                ok=True,
                status_code=200,
                json=lambda: {
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "output": [],
                    "usage": {
                        "input_tokens": 4584,
                        "output_tokens": 2000,
                        "total_tokens": 6584,
                        "output_tokens_details": {"reasoning_tokens": 2000},
                    },
                },
            )
            with self.assertLogs(coinlens_app.app.logger, level="WARNING") as logs:
                response = self.client.post(
                    "/api/identify-coin",
                    json={"front_image": JPEG_BASE64, "source": "camera"},
                    headers=self.auth_headers,
                )
        body = response.get_json()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(body["error"]["code"], "ai_incomplete")
        self.assertNotEqual(body["error"]["code"], "identification_failure")
        self.assertTrue(any(
            "incomplete_details" in message and "max_output_tokens" in message
            for message in logs.output
        ))
        mock_update.assert_called_once_with("usage-1", {"status": "error"})

    def test_identify_coin_incomplete_for_a_different_reason_still_falls_through(self):
        """Only incomplete_details.reason == "max_output_tokens" gets the
        dedicated ai_incomplete treatment - some other incomplete reason
        (with no usable output_text) still falls through to the existing
        generic empty-response handling, unchanged."""
        self._authenticate()
        coinlens_app.OPENAI_API_KEY = "test-key"

        with mock.patch.object(coinlens_app.requests, "post") as mock_post, \
             mock.patch.object(coinlens_app, "count_api_usage_since", return_value=0), \
             mock.patch.object(coinlens_app, "insert_api_usage", return_value={"id": "usage-1"}), \
             mock.patch.object(coinlens_app, "update_api_usage"):
            mock_post.return_value = mock.Mock(
                ok=True,
                status_code=200,
                json=lambda: {
                    "status": "incomplete",
                    "incomplete_details": {"reason": "content_filter"},
                    "output": [],
                },
            )
            response = self.client.post(
                "/api/identify-coin",
                json={"front_image": JPEG_BASE64, "source": "camera"},
                headers=self.auth_headers,
            )
        body = response.get_json()

        self.assertEqual(response.status_code, 422)
        self.assertEqual(body["error"]["code"], "identification_failure")

    def test_identify_coin_genuine_uncertain_identification_unchanged(self):
        """Completed response + genuinely uncertain identification must
        keep the existing 'Coin Not Recognized' flow (422/unidentifiable
        via identifiable=False), completely distinct from ai_incomplete -
        this is the "completed + uncertain" half of the required
        distinction, using an otherwise-valid low-confidence response."""
        self._authenticate()
        coinlens_app.OPENAI_API_KEY = "test-key"

        uncertain = {
            "status": "uncertain", "coin_name": "Unidentified coin",
            "country": "Unknown", "denomination": "Unknown", "year": "Unknown",
            "mint_mark": None, "estimated_grade": "Unknown", "confidence": 10,
            "description": "", "mint_errors": [], "varieties": None,
            "error_premium": False, "special_notes": "",
            "unidentifiable_reason": "The coin is too worn to identify confidently.",
            "alternatives": [],
        }
        with mock.patch.object(coinlens_app.requests, "post") as mock_post, \
             mock.patch.object(coinlens_app, "count_api_usage_since", return_value=0), \
             mock.patch.object(coinlens_app, "insert_api_usage", return_value={"id": "usage-1"}), \
             mock.patch.object(coinlens_app, "update_api_usage"):
            mock_post.return_value = mock.Mock(
                ok=True, status_code=200,
                json=lambda: {"status": "completed", "output_text": json.dumps(uncertain)},
            )
            response = self.client.post(
                "/api/identify-coin",
                json={"front_image": JPEG_BASE64, "source": "camera"},
                headers=self.auth_headers,
            )
        body = response.get_json()

        self.assertEqual(response.status_code, 422)
        self.assertFalse(body["identification"]["identifiable"])
        self.assertNotEqual(body.get("error", {}).get("code"), "ai_incomplete")

    def test_identify_coin_sends_low_reasoning_effort(self):
        """The model's default reasoning effort consumed the entire
        max_output_tokens budget on a real scan - explicitly request low
        effort rather than relying on whatever the default is."""
        self._authenticate()
        coinlens_app.OPENAI_API_KEY = "test-key"
        self.mock_persisted_scan()

        identification = {
            "status": "identified", "coin_name": "2012 United Kingdom 20 Pence",
            "country": "United Kingdom", "denomination": "20 pence", "year": "2012",
            "mint_mark": None, "estimated_grade": "VF-20", "confidence": 97,
            "description": "", "mint_errors": [], "varieties": None,
            "error_premium": False, "special_notes": "", "unidentifiable_reason": None,
            "alternatives": [],
        }
        with mock.patch.object(coinlens_app.requests, "post") as mock_post, \
             mock.patch.object(coinlens_app, "count_api_usage_since", return_value=0), \
             mock.patch.object(coinlens_app, "insert_api_usage", return_value={"id": "usage-1"}), \
             mock.patch.object(coinlens_app, "update_api_usage"):
            mock_post.return_value = mock.Mock(
                ok=True, status_code=200, json=lambda: {"status": "completed", "output_text": json.dumps(identification)},
            )
            self.client.post(
                "/api/identify-coin",
                json={"front_image": JPEG_BASE64, "source": "camera"},
                headers=self.auth_headers,
            )

        sent_payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_payload["reasoning"], {"effort": "low"})
        self.assertEqual(sent_payload["max_output_tokens"], 2000)

    # -- confidence-means-complete-identification (semantic fix) -----------
    # These exercise normalize_identification() directly with the shape a
    # real model response takes for each scenario, since the actual prompt
    # wording can't be asserted by calling a live model in a unit test.

    def test_normalize_identification_fully_identified_coin_is_high_confidence(self):
        data = {
            "status": "identified",
            "coin_name": "1965 United States Washington Quarter",
            "country": "United States",
            "denomination": "Quarter Dollar",
            "year": "1965",
            "mint_mark": "D",
            "estimated_grade": "VF-30",
            "confidence": 92,
            "description": "Clear obverse and reverse, legible date and mint mark.",
            "mint_errors": [],
            "varieties": None,
            "error_premium": False,
            "special_notes": "",
            "unidentifiable_reason": None,
            "alternatives": [],
            "observations": grounded_observations(
                "LIBERTY IN GOD WE TRUST 1965", "UNITED STATES OF AMERICA QUARTER DOLLAR", ["1965"],
                "UNITED STATES OF AMERICA", "QUARTER DOLLAR", "1965", color="silver-colored",
            ),
        }

        result = coinlens_app.normalize_identification(data)

        self.assertEqual(result["status"], "identified")
        self.assertTrue(result["identifiable"])
        self.assertGreaterEqual(result["confidence"], 70)
        self.assertEqual(result["year"], "1965")
        self.assertEqual(result["mint_mark"], "D")

    def test_normalize_identification_illegible_year_is_uncertain_and_low_confidence(self):
        # Mirrors the real production case this fix addresses: country and
        # denomination were clear (Hong Kong, 10 cents) but the year could
        # not be read, so confidence must be low and status uncertain -
        # not a high number attached to an incomplete identification.
        data = {
            "status": "uncertain",
            "coin_name": "Hong Kong 10 Cents",
            "country": "Hong Kong",
            "denomination": "10 Cents",
            "year": "Not legible",
            "mint_mark": None,
            "estimated_grade": "Unknown",
            "confidence": 15,
            "description": "Country and denomination are clear but the date is worn away.",
            "mint_errors": [],
            "varieties": None,
            "error_premium": False,
            "special_notes": "",
            "unidentifiable_reason": "The date is too worn to read confidently. A sharper, well-lit photo of the date would help.",
            "alternatives": [],
        }

        result = coinlens_app.normalize_identification(data)

        self.assertEqual(result["status"], "uncertain")
        self.assertFalse(result["identifiable"])
        self.assertLess(result["confidence"], coinlens_app.MIN_IDENTIFICATION_CONFIDENCE)
        # Country/denomination are still surfaced even though the overall
        # identification isn't complete enough to proceed to Numista.
        self.assertEqual(result["country"], "Hong Kong")
        self.assertEqual(result["denomination"], "10 Cents")

    def test_normalize_identification_non_coin_is_uncertain(self):
        data = {
            "status": "uncertain",
            "coin_name": None,
            "country": None,
            "denomination": None,
            "year": None,
            "mint_mark": None,
            "estimated_grade": None,
            "confidence": 3,
            "description": "This appears to be a button, not a coin.",
            "mint_errors": [],
            "varieties": None,
            "error_premium": False,
            "special_notes": "",
            "unidentifiable_reason": "This does not appear to be a coin.",
            "alternatives": [],
        }

        result = coinlens_app.normalize_identification(data)

        self.assertEqual(result["status"], "uncertain")
        self.assertFalse(result["identifiable"])
        self.assertLess(result["confidence"], coinlens_app.MIN_IDENTIFICATION_CONFIDENCE)
        self.assertEqual(result["country"], "Unknown")
        self.assertEqual(result["denomination"], "Unknown")

    def test_identify_coin_illegible_year_returns_422_without_numista(self):
        # End-to-end version of the middle case above: the full route must
        # still 422 and never reach Numista when the model (correctly, per
        # the updated prompt) reports low confidence for an incomplete id.
        self._authenticate()
        coinlens_app.OPENAI_API_KEY = "test-key"
        uncertain = {
            "coin_name": "Hong Kong 10 Cents", "country": "Hong Kong", "denomination": "10 Cents",
            "year": "Unknown", "mint_mark": None, "estimated_grade": "Unknown", "description": "",
            "mint_errors": [], "varieties": None, "error_premium": False, "special_notes": "",
            "status": "uncertain", "identifiable": False,
            "unidentifiable_reason": "The date is too worn to read confidently.", "confidence": 15, "alternatives": [],
        }
        with mock.patch.object(coinlens_app, "identify_coin_with_ai", return_value=uncertain), \
             mock.patch.object(coinlens_app, "insert_api_usage", return_value={"id": "usage-1"}), \
             mock.patch.object(coinlens_app, "count_api_usage_since", return_value=0), \
             mock.patch.object(coinlens_app, "update_api_usage") as mock_update, \
             mock.patch.object(coinlens_app, "search_numista_types") as mock_numista_search, \
             mock.patch.object(coinlens_app, "insert_scan") as mock_insert:
            response = self.client.post(
                "/api/identify-coin",
                json={"front_image": JPEG_BASE64, "source": "camera"},
                headers=self.auth_headers,
            )
        body = response.get_json()

        self.assertEqual(response.status_code, 422)
        self.assertEqual(body["identification"]["status"], "uncertain")
        self.assertLess(body["identification"]["confidence"], coinlens_app.MIN_IDENTIFICATION_CONFIDENCE)
        mock_numista_search.assert_not_called()
        mock_insert.assert_not_called()
        mock_update.assert_called_once_with("usage-1", {"status": "uncertain"})

    # -- build_coin_summary: the AI is prompted to embed its own "visual
    # estimate, not a professional certified grade" disclaimer directly in
    # estimated_grade - the summary must not append a second one on top. --

    def test_build_coin_summary_does_not_duplicate_a_grade_disclaimer_the_ai_already_included(self):
        identification = {
            "year": "2012", "country": "United Kingdom", "denomination": "20 pence",
            "estimated_grade": "VF-25 (visual estimate; not professionally certified)",
            "mint_errors": [],
        }
        summary = coinlens_app.build_coin_summary(identification, {"status": "unavailable"})
        self.assertIn("Estimated grade: VF-25 (visual estimate; not professionally certified).", summary)
        self.assertEqual(summary.count("visual estimate"), 1)
        self.assertNotIn("AI visual estimate, not a professional certified grade", summary)

    def test_build_coin_summary_shows_a_bare_grade_when_ai_omitted_a_disclaimer(self):
        identification = {
            "year": "2020", "country": "Canada", "denomination": "1 dollar",
            "estimated_grade": "MS-63", "mint_errors": [],
        }
        summary = coinlens_app.build_coin_summary(identification, {"status": "unavailable"})
        self.assertIn("Estimated grade: MS-63.", summary)

    # -- /api/badges/me: authoritative badge eligibility, identity only
    # from the verified JWT (g.user_id), never a client-supplied id. -----

    def test_badges_me_requires_auth(self):
        original_supabase_url = coinlens_auth.SUPABASE_URL
        coinlens_auth.SUPABASE_URL = TEST_SUPABASE_URL
        self.addCleanup(lambda: setattr(coinlens_auth, "SUPABASE_URL", original_supabase_url))

        response = self.client.get("/api/badges/me")
        self.assertEqual(response.status_code, 401)

    def test_badges_me_returns_the_expected_contract(self):
        self._authenticate()
        scans = [{"estimated_value": 5}] * 12
        with mock.patch.object(coinlens_app, "fetch_scans_for_user", return_value=scans) as mock_scans, \
             mock.patch.object(coinlens_app, "fetch_profile_created_at", return_value=None) as mock_profile:
            response = self.client.get("/api/badges/me", headers=self.auth_headers)
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIn("badge_count", body)
        self.assertIn("earned_badge_ids", body)
        self.assertIn("scan_10", body["earned_badge_ids"])
        self.assertIn("worth_50", body["earned_badge_ids"])
        self.assertEqual(body["badge_count"], len(body["earned_badge_ids"]))
        # Only the two trusted calls - never fetching anything about a
        # different user, never reading a client-supplied id.
        mock_scans.assert_called_once_with("user-123", coinlens_app.BADGE_SCAN_COLUMNS)
        mock_profile.assert_called_once_with("user-123")

    def test_badges_me_ignores_a_client_supplied_user_id(self):
        """Identity comes only from the verified JWT - a client can never
        request another user's badges by passing a different id."""
        self._authenticate()
        with mock.patch.object(coinlens_app, "fetch_scans_for_user", return_value=[]) as mock_scans, \
             mock.patch.object(coinlens_app, "fetch_profile_created_at", return_value=None):
            self.client.get("/api/badges/me?user_id=someone-elses-id", headers=self.auth_headers)
        mock_scans.assert_called_once_with("user-123", coinlens_app.BADGE_SCAN_COLUMNS)

    def test_badges_me_fetch_failure_returns_503(self):
        self._authenticate()
        with mock.patch.object(coinlens_app, "fetch_scans_for_user", side_effect=coinlens_app.SupabaseAdminError("boom")):
            response = self.client.get("/api/badges/me", headers=self.auth_headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"]["code"], "badges_fetch_failed")

    # -- /api/leaderboard: existing aggregate fields + an authoritative,
    # server-computed badge_count per row - batched scan fetch, no raw
    # scan data ever returned, same result regardless of viewer. --------

    LEADERBOARD_ROWS = [
        {
            "user_id": "lizard-id", "display_name": "lizard", "scan_count": 9,
            "total_value": 12.5, "avg_value": 1.39, "member_since": "2020-01-01T00:00:00+00:00",
        },
        {
            "user_id": "bro-id", "display_name": "bro", "scan_count": 1,
            "total_value": 0, "avg_value": 0, "member_since": "2026-09-01T00:00:00+00:00",
        },
    ]
    LEADERBOARD_SCANS = [
        {"user_id": "lizard-id", "denom_canonical": "dollar", "is_foreign": True, "estimated_value": 2.0},
        {"user_id": "lizard-id", "denom_canonical": "5-cents", "is_foreign": True, "estimated_value": 0.1},
        {"user_id": "bro-id", "denom_canonical": "penny", "is_foreign": False, "estimated_value": 0.01},
    ]

    def test_leaderboard_requires_auth(self):
        original_supabase_url = coinlens_auth.SUPABASE_URL
        coinlens_auth.SUPABASE_URL = TEST_SUPABASE_URL
        self.addCleanup(lambda: setattr(coinlens_auth, "SUPABASE_URL", original_supabase_url))

        response = self.client.get("/api/leaderboard")
        self.assertEqual(response.status_code, 401)

    def test_leaderboard_preserves_existing_fields_and_adds_badge_count(self):
        self._authenticate()
        with mock.patch.object(coinlens_app, "fetch_leaderboard_rows", return_value=self.LEADERBOARD_ROWS), \
             mock.patch.object(coinlens_app, "fetch_scans_for_users", return_value=self.LEADERBOARD_SCANS) as mock_batch:
            response = self.client.get("/api/leaderboard", headers=self.auth_headers)
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(body), 2)
        for row in body:
            for field in ("user_id", "display_name", "scan_count", "total_value", "avg_value", "member_since", "badge_count"):
                self.assertIn(field, row)

        # Exactly the expected authoritative counts for this fixture data.
        lizard_row = next(r for r in body if r["user_id"] == "lizard-id")
        bro_row = next(r for r in body if r["user_id"] == "bro-id")
        expected_lizard_count, _ = coinlens_app.evaluate_badges(
            [s for s in self.LEADERBOARD_SCANS if s["user_id"] == "lizard-id"], "2020-01-01T00:00:00+00:00",
        )
        expected_bro_count, _ = coinlens_app.evaluate_badges(
            [s for s in self.LEADERBOARD_SCANS if s["user_id"] == "bro-id"], "2026-09-01T00:00:00+00:00",
        )
        self.assertEqual(lizard_row["badge_count"], expected_lizard_count)
        self.assertEqual(bro_row["badge_count"], expected_bro_count)

        # One batched call for every user's scans, not one call per user.
        mock_batch.assert_called_once()
        requested_ids = mock_batch.call_args[0][0]
        self.assertCountEqual(requested_ids, ["lizard-id", "bro-id"])

    def test_leaderboard_never_returns_raw_scan_fields(self):
        self._authenticate()
        with mock.patch.object(coinlens_app, "fetch_leaderboard_rows", return_value=self.LEADERBOARD_ROWS), \
             mock.patch.object(coinlens_app, "fetch_scans_for_users", return_value=self.LEADERBOARD_SCANS):
            response = self.client.get("/api/leaderboard", headers=self.auth_headers)
        response_text = response.get_data(as_text=True)
        for leaked in ("denom_canonical", "estimated_value", "is_foreign", "local_hour", "local_date"):
            self.assertNotIn(leaked, response_text)

    def test_leaderboard_badge_count_is_independent_of_the_viewer(self):
        """The core regression requirement: badge_count(user X) must be
        identical no matter which authenticated user is looking."""
        with mock.patch.object(coinlens_app, "fetch_leaderboard_rows", return_value=self.LEADERBOARD_ROWS), \
             mock.patch.object(coinlens_app, "fetch_scans_for_users", return_value=self.LEADERBOARD_SCANS):
            self._authenticate()
            as_lizard = self.client.get("/api/leaderboard", headers=self.auth_headers).get_json()

            token, public_key = make_test_token(sub="bro-id")
            bro_headers = {"Authorization": f"Bearer {token}"}
            with mock.patch.object(coinlens_auth, "_get_signing_key", return_value=public_key):
                as_bro = self.client.get("/api/leaderboard", headers=bro_headers).get_json()

        self.assertEqual(as_lizard, as_bro)

    def test_leaderboard_fetch_failure_returns_503(self):
        self._authenticate()
        with mock.patch.object(coinlens_app, "fetch_leaderboard_rows", side_effect=coinlens_app.SupabaseAdminError("boom")):
            response = self.client.get("/api/leaderboard", headers=self.auth_headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"]["code"], "leaderboard_fetch_failed")


class CanonicalizeDenominationTests(unittest.TestCase):
    """Real production bug: "cent" is a substring of "cents", so any
    "N cents" denomination (Canada/Australia 5c/10c/25c, etc.) was
    misclassified as "penny" before the more specific nickel/dime/quarter
    checks ever got a chance - e.g. a real "Canada 5 cents" scan persisted
    denom_canonical="penny", which could falsely award type_penny/
    var_penny_streak. Only the literal word "penny", or an explicit
    numeric value of 1 ("1 cent"/"one cent" - the actual US penny), should
    land here now."""

    def test_explicit_penny_forms_still_recognized(self):
        for denom in ("1 cent", "one cent", "penny", "1 Cent", "Penny"):
            with self.subTest(denom=denom):
                self.assertEqual(coinlens_app.canonicalize_denomination(denom, ""), "penny")

    def test_wheat_penny_still_takes_precedence(self):
        self.assertEqual(coinlens_app.canonicalize_denomination("1 cent", "1946 Lincoln Wheat Cent"), "wheat-penny")

    def test_foreign_5_cents_is_not_penny(self):
        self.assertNotEqual(coinlens_app.canonicalize_denomination("Canada 5 cents", ""), "penny")
        self.assertNotEqual(coinlens_app.canonicalize_denomination("5 cents", ""), "penny")
        self.assertNotEqual(coinlens_app.canonicalize_denomination("5 cent", ""), "penny")

    def test_10_and_25_cents_are_not_penny(self):
        self.assertNotEqual(coinlens_app.canonicalize_denomination("10 cents", ""), "penny")
        self.assertNotEqual(coinlens_app.canonicalize_denomination("25 cents", ""), "penny")

    # -- Real production follow-up: the previous fix left an inconsistency
    # - "5 cents" fell through to a generic slug, but spelled-out "five
    # cents" still matched a parallel word-based check and became
    # "nickel". The same foreign coin must not earn a different (US-
    # specific) badge category depending only on whether OpenAI phrased
    # the face value as a digit or a word. Fixed by normalizing spelled-
    # out numbers to digits before any check runs, and by only ever
    # recognizing nickel/dime/quarter from an explicit coin-name word -
    # never from face value, digit or spelled-out, alone.

    def test_digit_and_word_face_values_are_now_equivalent(self):
        pairs = [
            ("5 cents", "five cents"),
            ("10 cents", "ten cents"),
            ("25 cents", "twenty-five cents"),
            ("25 cents", "twenty five cents"),
            ("1 cent", "one cent"),
        ]
        for digit_form, word_form in pairs:
            with self.subTest(digit_form=digit_form, word_form=word_form):
                self.assertEqual(
                    coinlens_app.canonicalize_denomination(digit_form, ""),
                    coinlens_app.canonicalize_denomination(word_form, ""),
                )

    def test_face_value_alone_never_implies_nickel_dime_or_quarter(self):
        for denom in ("5 cents", "five cents", "10 cents", "ten cents", "25 cents", "twenty-five cents"):
            with self.subTest(denom=denom):
                result = coinlens_app.canonicalize_denomination(denom, "")
                self.assertNotIn(result, ("penny", "nickel", "dime", "quarter"))

    def test_foreign_context_does_not_change_the_result(self):
        # canonicalize_denomination doesn't need country/context at all -
        # removing face-value inference entirely made the result already
        # country-agnostic, so a "Canada"/"foreign" coin_name changes
        # nothing here.
        self.assertEqual(
            coinlens_app.canonicalize_denomination("5 cents", "Canada 5 Cents"),
            coinlens_app.canonicalize_denomination("five cents", "Canada Five Cents"),
        )
        self.assertEqual(
            coinlens_app.canonicalize_denomination("10 cents", "Canada 10 Cents"),
            coinlens_app.canonicalize_denomination("ten cents", "Canada Ten Cents"),
        )
        self.assertEqual(
            coinlens_app.canonicalize_denomination("25 cents", "Foreign 25 Cents"),
            coinlens_app.canonicalize_denomination("twenty-five cents", "Foreign Twenty-Five Cents"),
        )

    def test_explicit_coin_name_words_still_recognized(self):
        for denom, expected in (("nickel", "nickel"), ("dime", "dime"), ("quarter", "quarter"), ("penny", "penny")):
            with self.subTest(denom=denom):
                self.assertEqual(coinlens_app.canonicalize_denomination(denom, ""), expected)

    def test_genuine_us_coin_still_recognized_via_explicit_coin_name(self):
        # A real US nickel/dime is still correctly tagged - not via face
        # value, but because a real identification names the coin
        # explicitly (as US coin identifications naturally do).
        self.assertEqual(coinlens_app.canonicalize_denomination("5 cents", "Jefferson Nickel"), "nickel")
        self.assertEqual(coinlens_app.canonicalize_denomination("10 cents", "Roosevelt Dime"), "dime")

    def test_2_dollars_still_maps_to_dollar(self):
        self.assertEqual(coinlens_app.canonicalize_denomination("2 dollars", ""), "dollar")
        self.assertEqual(coinlens_app.canonicalize_denomination("Hong Kong 2 dollars", ""), "dollar")

    def test_existing_denominations_unaffected(self):
        self.assertEqual(coinlens_app.canonicalize_denomination("dime", ""), "dime")
        self.assertEqual(coinlens_app.canonicalize_denomination("quarter", ""), "quarter")
        self.assertEqual(coinlens_app.canonicalize_denomination("half dollar", ""), "half-dollar")

    def test_unmatched_denomination_falls_back_to_a_slug(self):
        self.assertEqual(coinlens_app.canonicalize_denomination("Canada 5 cents", ""), "canada-5-cents")
        self.assertEqual(coinlens_app.canonicalize_denomination("20 pence", ""), "20-pence")


if __name__ == "__main__":
    unittest.main()
