"""
demo_mcp.py — drive the ACI MCP server exactly the way an AI host (Claude Code,
Cursor, Claude desktop) drives it: spawn it, do the JSON-RPC handshake over stdio,
list tools, and call them. Proves the AI bridge works end-to-end against a running
ACI service.

Prereq: an ACI service is running (py quickstart.py, or set ACI_URL).
Run:    py demos/demo_mcp.py
"""
import json
import os
import subprocess
import sys


def rpc(proc, msg):
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    if "id" not in msg:                 # notification: no response expected
        return None
    while True:
        line = proc.stdout.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r.get("id") == msg["id"]:
            return r


def text_of(resp):
    return resp["result"]["content"][0]["text"]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")   # so ψ etc. print on Windows consoles
    except Exception:
        pass
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.Popen(
        [sys.executable, "-m", "aci.mcp_server"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr,
        text=True, encoding="utf-8", cwd=root, env=dict(os.environ))
    try:
        init = rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                     "clientInfo": {"name": "demo", "version": "0"}}})
        si = init["result"]["serverInfo"]
        print(f"initialized: {si['name']} v{si['version']}  (protocol {init['result']['protocolVersion']})")
        rpc(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        tl = rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        print("tools the AI now has:", [t["name"] for t in tl["result"]["tools"]])

        print("\n--- AI writes a fact to your ACI ---")
        print(text_of(rpc(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": "aci_remember",
                         "arguments": {"content": "Devadipta's cognition framework is called UQRT-MCA."}}})))

        print("\n--- AI recalls from your ACI (no manual feeding) ---")
        print(text_of(rpc(proc, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
              "params": {"name": "aci_recall",
                         "arguments": {"query": "what is the user's framework called", "k": 3}}})))

        print("\n--- AI fact-checks a claim against your ACI ---")
        print(text_of(rpc(proc, {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
              "params": {"name": "aci_validate",
                         "arguments": {"statement": "The user's framework is called UQRT-MCA."}}})))
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        proc.terminate()


if __name__ == "__main__":
    main()
