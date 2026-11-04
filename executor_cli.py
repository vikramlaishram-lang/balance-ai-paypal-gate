from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from balance_paypal.config import load_local_env, paypal_credentials_available
from balance_paypal.executor import ExecutorError, TokenBoundExecutor
from balance_paypal.observed_executor import CollectorClient, ObservedExecutor, ObservedProvider, ObservationFailure
from balance_paypal.paypal import PayPalSandboxClient
from balance_paypal.security import external_path, read_key_file


@dataclass
class _EffectFreeProvider:
    """A provider-shaped tripwire used only by the credential-free preflight."""

    calls: int = 0
    last_response_metadata: dict | None = None

    def _refuse(self):
        self.calls += 1
        raise RuntimeError("Effect-free preflight refused an attempted provider dispatch.")

    def create_order(self, **kwargs):
        return self._refuse()

    def capture_order(self, order_id, request_id):
        return self._refuse()

    def get_order(self, order_id):
        return self._refuse()


def build_executor() -> ObservedExecutor:
    credential_path = os.environ.get("BALANCE_PAYPAL_CREDENTIAL_FILE", "").strip()
    token_path = os.environ.get("BALANCE_TOKEN_KEY_FILE", "").strip()
    if not credential_path or not token_path:
        raise RuntimeError("Executor requires external PayPal credential and token-key files.")
    credential_file = external_path(
        credential_path, project_root=ROOT, label="PayPal credential file"
    )
    token_file = external_path(token_path, project_root=ROOT, label="Gate token key")
    load_local_env(credential_file)
    if not paypal_credentials_available():
        raise RuntimeError("External credential file lacks PayPal Sandbox credentials.")
    collector_url = os.environ.get("BALANCE_EXECUTOR_COLLECTOR_URL", "").strip()
    collector_window = os.environ.get("BALANCE_EXECUTOR_COLLECTOR_WINDOW_ID", "").strip()
    if not collector_url or not collector_window:
        raise RuntimeError("v0.5.1 refuses to start without independent collector and window")
    observer = CollectorClient(collector_url, collector_window)
    provider = ObservedProvider(PayPalSandboxClient(), observer)
    return ObservedExecutor(
        TokenBoundExecutor(provider, read_key_file(token_file, label="Gate token key")),
        provider, observer,
    )


def build_effect_free_executor() -> tuple[ObservedExecutor, dict]:
    """Build the observation path without credentials, PayPal, or a valid token.

    The fixed in-memory key is deliberately unusable for live execution.  The preflight
    sends an invalid token, so request/refusal logging is exercised while the provider
    tripwire must remain untouched.
    """
    collector_url = os.environ.get("BALANCE_EXECUTOR_COLLECTOR_URL", "").strip()
    collector_window = os.environ.get("BALANCE_EXECUTOR_COLLECTOR_WINDOW_ID", "").strip()
    if not collector_url or not collector_window:
        raise RuntimeError("Effect-free Executor requires collector URL and window binding.")
    observer = CollectorClient(collector_url, collector_window)
    tripwire = _EffectFreeProvider()
    provider = ObservedProvider(tripwire, observer)
    executor = ObservedExecutor(
        TokenBoundExecutor(provider, b"v0.5.2-effect-free-preflight-key-not-for-live-use"),
        provider,
        observer,
    )
    return executor, {
        "mode": "effect-free-preflight",
        "collector_window_id": collector_window,
        "provider_tripwire_calls": lambda: tripwire.calls,
    }


def handler_for(executor, health_facts=None):
    health_facts = health_facts or {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/health":
                self.send_error(404)
                return
            facts = {
                key: (value() if callable(value) else value)
                for key, value in health_facts.items()
            }
            body = json.dumps({"ready": True, "pid": os.getpid(), **facts}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != "/execute":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                value = json.loads(self.rfile.read(length).decode("utf-8"))
                result = executor.execute(value["token"], value["request"])
                body = json.dumps(result, separators=(",", ":")).encode("utf-8")
                self.send_response(200)
            except (ExecutorError, ObservationFailure, KeyError, ValueError, json.JSONDecodeError) as exc:
                body = json.dumps({"error": str(exc)}).encode("utf-8")
                self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="v0.5.2 observed PayPal Sandbox Executor candidate")
    parser.add_argument("serve", nargs="?")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--effect-free-preflight",
        action="store_true",
        help="exercise collector binding and refusal logging without credentials or PayPal",
    )
    args = parser.parse_args()
    if args.effect_free_preflight:
        executor, health_facts = build_effect_free_executor()
        paypal_mode = "not-instantiated"
    else:
        executor = build_executor()
        health_facts = {"mode": "credential-bearing", "paypal_mode": "sandbox-only"}
        paypal_mode = "sandbox-only"
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port), handler_for(executor, health_facts)
    )
    print(json.dumps({"executor": "ready", "host": "127.0.0.1", "port": args.port,
                      "mode": health_facts["mode"], "paypal_mode": paypal_mode,
                      "credentials_printed": False}), flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
