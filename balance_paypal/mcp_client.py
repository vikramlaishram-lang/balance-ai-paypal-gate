from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


class MCPError(RuntimeError):
    pass


class ProposalMCPClient:
    """Minimal stdio MCP client that deliberately strips credential-bearing environment keys."""

    def __init__(self, database: Path, server_script: Path):
        allowed_names = {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "PYTHONUTF8"}
        child_env = {key: value for key, value in os.environ.items() if key.upper() in allowed_names}
        self.process = subprocess.Popen(
            [sys.executable, "-I", "-B", str(server_script), "--db", str(database)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=child_env,
        )
        self._next_id = 1
        self._request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "balance-qwen-agent", "version": "0.1.0"},
            },
        )
        self._notify("notifications/initialized", {})

    def _write(self, value: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(value, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        message_id = self._next_id
        self._next_id += 1
        self._write({"jsonrpc": "2.0", "id": message_id, "method": method, "params": params})
        assert self.process.stdout is not None
        raw = self.process.stdout.readline()
        if not raw:
            detail = self.process.stderr.read() if self.process.stderr else ""
            raise MCPError(f"Proposal MCP server stopped unexpectedly. {detail}".strip())
        response = json.loads(raw)
        if response.get("id") != message_id or "error" in response:
            raise MCPError(str(response.get("error", "Invalid MCP response")))
        return response["result"]

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def call_tool(self, name: str, arguments: dict[str, str]) -> dict[str, Any]:
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        return result["structuredContent"]

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        self.process.wait(timeout=5)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

