"""
aci-doctor — one-command health check for an AIOS / ACI install.

Verifies, in order, everything a working MCP wedge needs:
  1. Python version + core deps
  2. the ACI service is up (and reports monads / embedder)
  3. the MCP server imports and exposes its tools
  4. the MCP stdio handshake actually works (spawns the server, does initialize +
     tools/list over JSON-RPC — the real protocol path an AI client uses)
  5. whether ACI is registered in a known MCP client config

Prints a clear PASS / WARN / FAIL line per check and exits non-zero if anything
essential failed — so it doubles as the pre-launch "clean-machine" gate.

    aci-doctor            # check localhost:7077
    aci-doctor --url http://127.0.0.1:7077
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys

OK, WARN, FAIL = "PASS", "WARN", "FAIL"
_results = []


def _log(status, name, detail=""):
    _results.append(status)
    tag = {OK: "PASS", WARN: "WARN", FAIL: "FAIL"}[status]
    print(f"  [{tag}] {name}" + (f" — {detail}" if detail else ""))


def check_python():
    v = sys.version_info
    if v >= (3, 9):
        _log(OK, "Python", f"{v.major}.{v.minor}.{v.micro}")
    else:
        _log(FAIL, "Python", f"{v.major}.{v.minor} < 3.9 required")


def check_deps():
    for mod, essential in (("numpy", True), ("pypdf", True), ("sentence_transformers", False)):
        try:
            __import__(mod)
            _log(OK, f"dep: {mod}")
        except Exception:
            _log(FAIL if essential else WARN, f"dep: {mod}",
                 "missing" if essential else "optional (semantic search) — pip install sentence-transformers")


def check_service(url):
    try:
        from aci.client import ACIClient
        h = ACIClient(url, timeout=8).health()
        _log(OK, "ACI service", f"{url} · {h.get('monads', '?')} monads · embedder={h.get('embedder', '?')}"
             + (" · PAUSED" if h.get("paused") else ""))
        return True
    except Exception as e:
        _log(FAIL, "ACI service", f"not reachable at {url} — start it with `aci serve`  ({type(e).__name__})")
        return False


def check_mcp_import():
    try:
        from aci import mcp_server
        n = len(getattr(mcp_server, "TOOLS", []))
        _log(OK, "MCP server import", f"{n} tools")
    except Exception as e:
        _log(FAIL, "MCP server import", f"{type(e).__name__}: {e}")
    try:
        from aci import mcp_setup  # noqa: F401
        _log(OK, "MCP setup import")
    except Exception as e:
        _log(WARN, "MCP setup import", f"{type(e).__name__}: {e}")


def check_handshake(url):
    """Spawn the real MCP server and do initialize + tools/list over stdio — the exact
    path an AI client uses. This is the check that proves the wedge actually works."""
    try:
        env = {**os.environ, "ACI_URL": url}
        p = subprocess.Popen([sys.executable, "-m", "aci.mcp_server"],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, encoding="utf-8", env=env)
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05",
                           "clientInfo": {"name": "aci-doctor", "version": "1"}}}
        lst = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        out, err = p.communicate(json.dumps(init) + "\n" + json.dumps(lst) + "\n", timeout=25)
        lines = [json.loads(ln) for ln in out.splitlines() if ln.strip()]
        by_id = {m.get("id"): m for m in lines}
        proto = (by_id.get(1) or {}).get("result", {}).get("protocolVersion")
        tools = (by_id.get(2) or {}).get("result", {}).get("tools", [])
        if proto and tools:
            _log(OK, "MCP handshake", f"protocol {proto} · {len(tools)} tools listed over stdio")
        else:
            _log(FAIL, "MCP handshake", f"unexpected response (stderr: {err.strip()[:120]})")
    except Exception as e:
        _log(FAIL, "MCP handshake", f"{type(e).__name__}: {e}")


def check_client_config():
    from aci.mcp_setup import CLIENTS, SERVER_KEY
    found = []
    for name, pathfn in CLIENTS.items():
        path = pathfn()
        try:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    if SERVER_KEY in (json.load(f).get("mcpServers") or {}):
                        found.append(name)
        except Exception:
            pass
    if found:
        _log(OK, "MCP client config", "registered in: " + ", ".join(found))
    else:
        _log(WARN, "MCP client config", "not registered yet — run `aci-mcp-setup`")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="aci-doctor", description="AIOS / ACI health check.")
    ap.add_argument("--url", default=os.environ.get("ACI_URL", "http://127.0.0.1:7077"))
    a = ap.parse_args(argv)

    print("AIOS / ACI health check\n" + "-" * 40)
    check_python()
    check_deps()
    up = check_service(a.url)
    check_mcp_import()
    if up:
        check_handshake(a.url)
    else:
        _log(WARN, "MCP handshake", "skipped — service down")
    check_client_config()

    fails = _results.count(FAIL)
    warns = _results.count(WARN)
    print("-" * 40)
    verdict = "READY" if fails == 0 else "NOT READY"
    print(f"{verdict} — {_results.count(OK)} pass, {warns} warn, {fails} fail")
    if fails == 0 and warns == 0:
        print("Everything green. Safe to launch.")
    elif fails == 0:
        print("Essentials OK; warnings are non-blocking (optional features / setup steps).")
    else:
        print("Fix the FAIL items before launching.")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
