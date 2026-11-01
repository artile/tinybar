#!/usr/bin/env python3
"""Limits-only view of CLIProxyAPI. Python 3.11+, standard library only."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import threading
import time
import tomllib
import urllib.error
import urllib.request
from urllib.parse import urlsplit

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
MAX_BODY = 2 * 1024 * 1024


def timestamp():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def text(value, limit=128):
    return "".join(c for c in str(value or "") if c.isprintable())[:limit].strip()


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def clean_usage(raw):
    """Copy only fields the limits UI uses, never arbitrary upstream fields."""
    if not isinstance(raw, dict):
        raise ValueError("invalid usage")
    result = {}
    for key in ("five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet"):
        window = raw.get(key)
        if isinstance(window, dict) and number(window.get("utilization")):
            result[key] = {"utilization": max(0, min(100, window["utilization"]))}
            if isinstance(window.get("resets_at"), str):
                result[key]["resets_at"] = text(window["resets_at"], 64)
    limits = []
    for item in raw.get("limits") or []:
        if not isinstance(item, dict) or not number(item.get("percent")):
            continue
        scope = item.get("scope")
        model = scope.get("model") if isinstance(scope, dict) else None
        if not isinstance(model, dict):
            continue
        entry = {"percent": max(0, min(100, item["percent"])),
                 "scope": {"model": {k: text(model[k]) for k in ("id", "display_name") if k in model}}}
        for key in ("kind", "group", "resets_at"):
            if isinstance(item.get(key), str):
                entry[key] = text(item[key])
        if isinstance(item.get("is_active"), bool):
            entry["is_active"] = item["is_active"]
        limits.append(entry)
    if limits:
        result["limits"] = limits[:50]
    extra = raw.get("extra_usage")
    if isinstance(extra, dict) and isinstance(extra.get("is_enabled"), bool):
        result["extra_usage"] = {"is_enabled": extra["is_enabled"]}
        for key in ("used_credits", "monthly_limit"):
            if number(extra.get(key)):
                result["extra_usage"][key] = max(0, extra[key])
        if isinstance(extra.get("currency"), str):
            result["extra_usage"]["currency"] = text(extra["currency"], 8)
    if not any(k in result for k in ("five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet", "limits")):
        raise ValueError("no limit windows")
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Bridge:
    def __init__(self, config, request=None, clock=time.monotonic):
        base = config["management_url"].rstrip("/")
        url = urlsplit(base)
        if url.scheme != "http" or url.hostname not in ("127.0.0.1", "localhost", "::1") or url.username or url.password or url.query or url.fragment:
            raise ValueError("management_url must use local HTTP")
        self.base = base
        self.key_file = Path(config["management_key_file"])
        self.interval = max(300, int(config.get("cache_seconds", 300)))
        self.request = request or self._request
        self.clock = clock
        self.lock = threading.Lock()
        self.cached = None
        self.next_poll = 0
        self.retry_at = {}
        self.previous = {}
        self.generations = {}

    def _request(self, path, payload=None):
        key = self.key_file.read_text().strip()
        if not key:
            raise ValueError("missing management key")
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(self.base + path, data=data, headers={
            "Authorization": "Bearer " + key, "Content-Type": "application/json"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=35) as response:
            body = response.read(MAX_BODY + 1)
            if len(body) > MAX_BODY:
                raise ValueError("response too large")
            return json.loads(body)

    def _account(self, entry):
        identity = str(entry.get("id") or entry.get("name") or "")
        index = entry.get("auth_index")
        if not identity or index is None or not str(index).strip():
            raise ValueError("account has no identity")
        account_id = hashlib.sha256(("claude:" + identity).encode()).hexdigest()[:24]
        # A new login must not inherit a pause from the previous credential file.
        # In-memory status changes alone do not invalidate a provider's retry delay.
        generation = tuple(str(entry.get(field) or "") for field in ("auth_index", "modtime", "last_refresh"))
        previous_generation = self.generations.get(account_id)
        if previous_generation is not None and previous_generation != generation:
            self.retry_at.pop(account_id, None)
            self.previous.pop(account_id, None)
        self.generations[account_id] = generation
        account = {"id": account_id, "label": text(entry.get("label")) or text(entry.get("email")) or "Claude " + account_id[:6],
                   "fetched_at": timestamp()}
        if self.clock() < self.retry_at.get(account_id, 0) and account_id in self.previous:
            return {**self.previous[account_id], "label": account["label"]}
        try:
            response = self.request("/api-call", {
                "auth_index": str(index), "method": "GET", "url": USAGE_URL,
                "header": {"Authorization": "Bearer $TOKEN$", "Accept": "application/json",
                           "Content-Type": "application/json", "anthropic-beta": "oauth-2025-04-20"}})
            status = response.get("status_code")
            if status in (401, 403):
                account["error"] = {"code": "login_expired"}
            elif status == 429:
                headers = response.get("header") or {}
                retry = next((v for k, v in headers.items() if k.lower() == "retry-after"), None)
                if isinstance(retry, list):
                    retry = retry[0] if retry else None
                try:
                    try:
                        seconds = float(retry)
                    except (TypeError, ValueError):
                        seconds = (parsedate_to_datetime(str(retry)) - datetime.now(timezone.utc)).total_seconds()
                    if not math.isfinite(seconds):
                        raise ValueError()
                    seconds = max(300, seconds)
                except (TypeError, ValueError, OverflowError):
                    seconds = 300
                account["error"] = {"code": "rate_limited", "retry_after_seconds": seconds}
                self.retry_at[account_id] = self.clock() + seconds
            elif status == 200:
                raw = response.get("body")
                account["usage"] = clean_usage(json.loads(raw) if isinstance(raw, str) else raw)
            else:
                account["error"] = {"code": "upstream_error"}
        except Exception:
            # Do not expose management errors, upstream bodies, URLs, or credentials.
            account["error"] = {"code": "upstream_error"}
        return account

    def accounts(self):
        with self.lock:
            if self.cached is not None and self.clock() < self.next_poll:
                return self.cached
            entries = self.request("/auth-files").get("files")
            if not isinstance(entries, list):
                raise ValueError("invalid account list")
            entries = [e for e in entries if isinstance(e, dict) and
                       (e.get("provider") or e.get("type")) == "claude" and not e.get("disabled")]
            if len(entries) > 100:
                raise ValueError("too many accounts")
            with ThreadPoolExecutor(max_workers=4) as pool:
                accounts = list(pool.map(self._account, entries))
            accounts.sort(key=lambda a: (a["label"].casefold(), a["id"]))
            if len({a["id"] for a in accounts}) != len(accounts):
                raise ValueError("duplicate account identity")
            self.previous = {a["id"]: a for a in accounts}
            self.retry_at = {k: v for k, v in self.retry_at.items() if k in self.previous}
            self.generations = {k: v for k, v in self.generations.items() if k in self.previous}
            self.cached = {"schema_version": 1, "accounts": accounts}
            self.next_poll = self.clock() + self.interval
            return self.cached


def handler_for(bridge):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, value):
            body = json.dumps(value, allow_nan=False, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/healthz":
                self.reply(200, {"status": "ok"})
            elif self.path == "/v1/claude/accounts":
                try:
                    self.reply(200, bridge.accounts())
                except Exception:
                    self.reply(503, {"error": "accounts_unavailable"})
            else:
                self.reply(404, {"error": "not_found"})

        def method_not_allowed(self):
            self.reply(405, {"error": "read_only"})

        do_POST = do_PUT = do_PATCH = do_DELETE = method_not_allowed
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    with open(args.config, "rb") as source:
        config = tomllib.load(source)
    host = config.get("listen_host", "127.0.0.1")
    if host not in ("127.0.0.1", "localhost"):
        parser.error("listen_host must be loopback; use an SSH tunnel for remote clients")
    server = ThreadingHTTPServer((host, int(config.get("listen_port", 18767))), handler_for(Bridge(config)))
    server.serve_forever(poll_interval=1)


if __name__ == "__main__":
    main()
