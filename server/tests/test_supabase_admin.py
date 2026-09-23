import os
import sys
import unittest
from unittest import mock

SERVER_DIR = os.path.dirname(os.path.dirname(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import supabase_admin


def _response(status, json_data=None, text=""):
    resp = mock.Mock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.text = text
    resp.json.return_value = json_data if json_data is not None else []
    resp.headers = {}
    return resp


class GatewayRetryTests(unittest.TestCase):
    """Supabase's REST gateway occasionally returns a transient 502/503/504
    (e.g. a project waking from a cold state) with no data or auth problem
    at all - insert_scan/insert_api_usage/count_api_usage_since should retry
    a couple of times instead of failing the whole request over it."""

    def setUp(self):
        self._orig_url = supabase_admin.SUPABASE_URL
        self._orig_key = supabase_admin.SUPABASE_SERVICE_ROLE_KEY
        supabase_admin.SUPABASE_URL = "https://test.supabase.co"
        supabase_admin.SUPABASE_SERVICE_ROLE_KEY = "test-service-role-key"
        self.addCleanup(lambda: setattr(supabase_admin, "SUPABASE_URL", self._orig_url))
        self.addCleanup(lambda: setattr(supabase_admin, "SUPABASE_SERVICE_ROLE_KEY", self._orig_key))
        sleep_patcher = mock.patch.object(supabase_admin.time, "sleep")
        self.mock_sleep = sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)

    def test_insert_scan_retries_once_on_transient_504_then_succeeds(self):
        row = {"id": "scan-1"}
        responses = [_response(504, text="Gateway Timeout"), _response(201, json_data=[row])]
        with mock.patch.object(supabase_admin.requests, "post", side_effect=responses) as mock_post:
            result = supabase_admin.insert_scan({"user_id": "user-1"})
        self.assertEqual(result, row)
        self.assertEqual(mock_post.call_count, 2)
        self.mock_sleep.assert_called_once()

    def test_insert_scan_gives_up_after_max_retries_on_persistent_503(self):
        responses = [_response(503, text="Service Unavailable") for _ in range(3)]
        with mock.patch.object(supabase_admin.requests, "post", side_effect=responses) as mock_post:
            with self.assertRaises(supabase_admin.SupabaseAdminError):
                supabase_admin.insert_scan({"user_id": "user-1"})
        self.assertEqual(mock_post.call_count, 3)
        self.assertEqual(self.mock_sleep.call_count, 2)

    def test_insert_scan_does_not_retry_a_real_client_error(self):
        responses = [_response(400, text="Bad Request")]
        with mock.patch.object(supabase_admin.requests, "post", side_effect=responses) as mock_post:
            with self.assertRaises(supabase_admin.SupabaseAdminError):
                supabase_admin.insert_scan({"user_id": "user-1"})
        self.assertEqual(mock_post.call_count, 1)
        self.mock_sleep.assert_not_called()

    def test_insert_api_usage_retries_on_transient_502_then_succeeds(self):
        row = {"id": "usage-1"}
        responses = [_response(502, text="Bad Gateway"), _response(201, json_data=[row])]
        with mock.patch.object(supabase_admin.requests, "post", side_effect=responses) as mock_post:
            result = supabase_admin.insert_api_usage({"user_id": "user-1"})
        self.assertEqual(result, row)
        self.assertEqual(mock_post.call_count, 2)

    def test_count_api_usage_since_retries_on_transient_503_then_succeeds(self):
        ok_response = _response(200, json_data=[])
        ok_response.headers = {"Content-Range": "0-0/7"}
        responses = [_response(503, text="Service Unavailable"), ok_response]
        with mock.patch.object(supabase_admin.requests, "get", side_effect=responses) as mock_get:
            result = supabase_admin.count_api_usage_since("user-1", "2026-01-01T00:00:00+00:00")
        self.assertEqual(result, 7)
        self.assertEqual(mock_get.call_count, 2)


if __name__ == "__main__":
    unittest.main()
