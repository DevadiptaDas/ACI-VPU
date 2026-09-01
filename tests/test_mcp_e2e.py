"""
End-to-end MCP smoke test — drives the real `aci.mcp_server` over stdio JSON-RPC,
exactly the way an AI client (Claude Desktop / Cursor) does:

    initialize  ->  tools/list  ->  tools/call(aci_recall)

Proves the full protocol path works, not just the internals. READ-ONLY (a single
aci_recall) so it never writes to or pollutes the store. Requires the ACI service
running at $ACI_URL (default 127.0.0.1:7077).

Run directly:   py tests/test_mcp_e2e.py
Or via pytest:  pytest tests/test_mcp_e2e.py
"""
from __future__ import annotations
import json
import os
import subprocess
import sys

URL = os.environ.get("ACI_URL", "http://127.0.0.1:7077")
PROTOCOL = "2024-11-05"


def _drive(messages, timeout=30):
    """Send a list of JSON-RPC messages to a fresh mcp_server over stdio; return
    {id: response}. One process, messages piped in order, all output collected."""
    env = {**os.environ, "ACI_URL": URL}
    p = subprocess.Popen([sys.executable, "-m", "aci.mcp_server"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding="utf-8", env=env,
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    payload = "".join(json.dumps(m) + "\n" for m in messages)
    out, err = p.communicate(payload, timeout=timeout)
    responses = {}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            m = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "id" in m:
            responses[m["id"]] = m
    return responses, err


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": PROTOCOL,
                   "clientInfo": {"name": "e2e-test", "version": "1"}}}
LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
CALL = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "aci_recall", "arguments": {"query": "test connectivity probe", "k": 1}}}


def run():
    resp, err = _drive([INIT, LIST, CALL])

    # 1. initialize handshake
    init = resp.get(1, {}).get("result", {})
    assert init.get("protocolVersion"), f"no protocolVersion in initialize response (stderr: {err[:200]})"
    assert init.get("serverInfo", {}).get("name") == "aci-vpu", f"bad serverInfo: {init.get('serverInfo')}"
    proto = init["protocolVersion"]

    # 2. tools/list
    tools = resp.get(2, {}).get("result", {}).get("tools", [])
    names = {t["name"] for t in tools}
    assert "aci_recall" in names and "aci_remember" in names, f"tools missing: {sorted(names)}"

    # 3. tools/call (read-only recall) — must return content, no protocol error
    call = resp.get(3, {})
    assert "error" not in call, f"tools/call JSON-RPC error: {call.get('error')}"
    content = call.get("result", {}).get("content", [])
    assert content and content[0].get("type") == "text", f"no text content: {call}"

    print(f"[OK] initialize   -> protocol {proto}, server 'aci-vpu'")
    print(f"[OK] tools/list   -> {len(tools)} tools ({', '.join(sorted(names))[:80]}…)")
    print(f"[OK] tools/call   -> aci_recall returned text ({len(content[0]['text'])} chars, read-only)")
    print("\nMCP end-to-end: PASS — full stdio protocol path works.")
    return True


# pytest entry points
def test_initialize():
    resp, err = _drive([INIT])
    assert resp.get(1, {}).get("result", {}).get("protocolVersion"), err[:200]


def test_tools_list():
    resp, _ = _drive([INIT, LIST])
    names = {t["name"] for t in resp.get(2, {}).get("result", {}).get("tools", [])}
    assert {"aci_recall", "aci_remember"} <= names


def test_tool_call_readonly():
    resp, _ = _drive([INIT, CALL])
    assert "error" not in resp.get(3, {})
    assert resp[3]["result"]["content"][0]["type"] == "text"


if __name__ == "__main__":
    try:
        run()
    except AssertionError as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        raise SystemExit(1)
