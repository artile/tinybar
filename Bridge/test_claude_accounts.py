import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from claude_accounts import Bridge, clean_usage, handler_for, USAGE_URL


CONFIG = {"management_url": "http://127.0.0.1:8317/v0/management", "management_key_file": "/unused"}


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.calls = []
        self.entries = [{"id": "account-a", "auth_index": "first", "provider": "claude", "email": "one@example.invalid"},
                        {"id": "account-b", "auth_index": "second", "provider": "claude", "email": "two@example.invalid"},
                        {"id": "disabled", "auth_index": "off", "provider": "claude", "disabled": True},
                        {"id": "codex", "auth_index": "other", "provider": "codex"}]
        self.status = {"first": 200, "second": 200}
        self.fail_list = False
        self.retry = "1200"
        self.bridge = Bridge(CONFIG, request=self.request, clock=lambda: self.now)

    def request(self, path, payload=None):
        self.calls.append((path, payload))
        if path == "/auth-files":
            if self.fail_list:
                raise ValueError("a private management error")
            return {"files": self.entries}
        self.assertEqual(path, "/api-call")
        self.assertEqual(payload["method"], "GET")
        self.assertEqual(payload["url"], USAGE_URL)
        self.assertEqual(payload["header"]["Authorization"], "Bearer $TOKEN$")
        return {"status_code": self.status[payload["auth_index"]], "header": {"Retry-After": [self.retry]},
                "body": json.dumps({"five_hour": {"utilization": 25, "resets_at": "2030-01-01T01:00:00Z"},
                                    "access_token": "NEVER-EXPOSE", "refresh_token": "NEVER-EXPOSE"})}

    def test_separate_accounts_use_selected_credentials_and_never_expose_tokens(self):
        result = self.bridge.accounts()
        self.assertEqual(len(result["accounts"]), 2)
        self.assertEqual(len({a["id"] for a in result["accounts"]}), 2)
        self.assertEqual({p["auth_index"] for _, p in self.calls if p}, {"first", "second"})
        self.assertNotIn("NEVER-EXPOSE", json.dumps(result))
        self.assertNotIn("auth_index", json.dumps(result))
        self.assertNotIn("$TOKEN$", json.dumps(result))

    def test_cache_retains_observation_time_and_avoids_duplicate_polls(self):
        first = self.bridge.accounts()
        self.now = 299
        self.assertEqual(self.bridge.accounts(), first)
        self.assertEqual(len(self.calls), 3)
        self.now = 301
        self.bridge.accounts()
        self.assertEqual(len(self.calls), 6)

    def test_one_failed_account_does_not_hide_the_other(self):
        self.status["first"] = 401
        accounts = self.bridge.accounts()["accounts"]
        self.assertEqual(accounts[0]["error"]["code"], "login_expired")
        self.assertIn("usage", accounts[1])

    def test_rate_limit_delays_only_that_account(self):
        self.status["first"] = 429
        self.bridge.accounts()
        self.now = 301
        self.bridge.accounts()
        attempts = [p["auth_index"] for _, p in self.calls if p]
        self.assertEqual(attempts.count("first"), 1)
        self.assertEqual(attempts.count("second"), 2)
        self.now = 1201
        self.bridge.accounts()
        self.assertEqual([p["auth_index"] for _, p in self.calls if p].count("first"), 2)

    def test_identity_survives_label_change_and_removal_is_reported(self):
        first = self.bridge.accounts()["accounts"][0]["id"]
        self.entries[0]["label"] = "Renamed"
        self.entries = self.entries[:1]
        self.now = 301
        accounts = self.bridge.accounts()["accounts"]
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["id"], first)

    def test_relogin_clears_only_the_changed_accounts_old_pause(self):
        self.status = {"first": 429, "second": 429}
        self.bridge.accounts()
        self.entries[0]["modtime"] = "2030-01-01T00:05:00Z"
        self.status["first"] = 200
        self.now = 301
        accounts = self.bridge.accounts()["accounts"]
        self.assertIn("usage", accounts[0])
        self.assertEqual(accounts[1]["error"]["code"], "rate_limited")
        attempts = [p["auth_index"] for _, p in self.calls if p]
        self.assertEqual(attempts.count("first"), 2)
        self.assertEqual(attempts.count("second"), 1)

    def test_refresh_metadata_change_is_detected_without_resetting_account_identity(self):
        self.status["first"] = 429
        account_id = self.bridge.accounts()["accounts"][0]["id"]
        self.entries[0]["last_refresh"] = "2030-01-01T00:05:00Z"
        self.status["first"] = 200
        self.now = 301
        account = self.bridge.accounts()["accounts"][0]
        self.assertEqual(account["id"], account_id)
        self.assertIn("usage", account)

    def test_runtime_status_updates_do_not_bypass_provider_pause(self):
        self.status["first"] = 429
        self.bridge.accounts()
        self.entries[0]["updated_at"] = "2030-01-01T00:05:00Z"
        self.entries[0]["status"] = "active"
        self.now = 301
        self.bridge.accounts()
        attempts = [p["auth_index"] for _, p in self.calls if p]
        self.assertEqual(attempts.count("first"), 1)

    def test_relogin_still_honors_a_new_rate_limit_response(self):
        self.status["first"] = 429
        self.bridge.accounts()
        self.entries[0]["modtime"] = "2030-01-01T00:05:00Z"
        self.now = 301
        self.bridge.accounts()
        self.now = 602
        self.bridge.accounts()
        attempts = [p["auth_index"] for _, p in self.calls if p]
        self.assertEqual(attempts.count("first"), 2)

    def test_retry_after_http_date_and_long_delays_are_not_shortened(self):
        self.status["first"] = 429
        self.retry = format_datetime(datetime.now(timezone.utc) + timedelta(days=2), usegmt=True)
        result = self.bridge.accounts()["accounts"][0]
        self.assertGreater(result["error"]["retry_after_seconds"], 86400)
        self.now = 90000
        self.bridge.accounts()
        self.assertEqual([p["auth_index"] for _, p in self.calls if p].count("first"), 1)

    def test_management_failure_does_not_report_old_readings_as_fresh(self):
        self.bridge.accounts()
        self.now = 301
        self.fail_list = True
        with self.assertRaises(ValueError):
            self.bridge.accounts()

    def test_usage_allowlist_removes_nested_secrets_and_rejects_empty_or_nonfinite(self):
        self.assertEqual(clean_usage({"five_hour": {"utilization": 120, "token": "secret"}, "secret": "secret"}),
                         {"five_hour": {"utilization": 100}})
        for payload in [{}, {"five_hour": {"utilization": float("nan")}}, {"five_hour": {"utilization": True}}]:
            with self.assertRaises(ValueError):
                clean_usage(payload)

    def test_http_routes_cannot_forward_arbitrary_or_mutating_requests(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.bridge))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}"
        try:
            with urllib.request.urlopen(url + "/v1/claude/accounts") as response:
                self.assertEqual(len(json.load(response)["accounts"]), 2)
            before = len(self.calls)
            for method, path, status in [("POST", "/v1/claude/accounts", 405), ("DELETE", "/auth-files", 405),
                                         ("GET", "/api-call", 404), ("GET", "/v1/claude/accounts?url=evil", 404)]:
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(urllib.request.Request(url + path, method=method))
                self.assertEqual(caught.exception.code, status)
                caught.exception.close()
            self.assertEqual(len(self.calls), before)
            self.fail_list = True
            self.now = 301
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(url + "/v1/claude/accounts")
            self.assertEqual(caught.exception.code, 503)
            self.assertNotIn(b"private", caught.exception.read())
            caught.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_management_key_cannot_go_to_a_remote_origin(self):
        for url in ["http://remote.invalid", "https://remote.invalid", "http://user@localhost", "http://localhost?url=remote"]:
            with self.assertRaises(ValueError):
                Bridge({**CONFIG, "management_url": url})


if __name__ == "__main__":
    unittest.main()
