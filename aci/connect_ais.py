"""
Auto-connect ACI to the MCP-capable AI tools on this machine (#auto-connect).

Detects installed AI tools that speak MCP (Claude Code, Claude Desktop, Codex,
Windsurf, Cursor) and registers ACI's MCP server into each one's config — so they
all use ACI automatically from their next launch, with no per-tool setup.

Safe: backs up each config before editing, MERGES (never clobbers other servers),
re-validates after writing, and supports --remove. Honest scope: only tools that
support MCP and that we know the config path for; takes effect on the tool's next
restart; non-MCP / closed apps can't be auto-connected this way.

    aci connect-ais            # wire every detected MCP tool
    aci connect-ais --remove   # unwire
"""
from __future__ import annotations
import json
import os
import shutil

SERVER_NAME = "aci"


def _repo():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _entry():
    return {"command": "py",
            "args": [os.path.join(_repo(), "mcp_aci.py")],
            "env": {"ACI_URL": "http://127.0.0.1:7077"}}


def _json_clients():
    home = os.path.expanduser("~")
    appdata = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
    return [
        ("Claude Code", os.path.join(home, ".claude.json")),
        ("Claude Desktop", os.path.join(appdata, "Claude", "claude_desktop_config.json")),
        ("Windsurf", os.path.join(home, ".codeium", "windsurf", "mcp_config.json")),
        ("Cursor", os.path.join(home, ".cursor", "mcp.json")),
    ]


def _codex_path():
    return os.path.join(os.path.expanduser("~"), ".codex", "config.toml")


def _merge_json(path, remove):
    if not os.path.exists(path):
        return "not installed"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return f"skipped (unreadable: {str(e)[:40]})"
    if not isinstance(data, dict):
        return "skipped (unexpected format)"
    shutil.copy(path, path + ".aci.bak")
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
        data["mcpServers"] = servers
    if remove:
        if SERVER_NAME not in servers:
            return "was not connected"
        servers.pop(SERVER_NAME, None)
    else:
        servers[SERVER_NAME] = _entry()
    tmp = path + ".aci.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    with open(tmp, "r", encoding="utf-8") as f:        # re-validate before swap
        json.load(f)
    os.replace(tmp, path)
    return "disconnected" if remove else "connected"


def _merge_codex(remove):
    path = _codex_path()
    if not os.path.exists(os.path.dirname(path)):
        return "not installed"
    block_header = f"[mcp_servers.{SERVER_NAME}]"
    existing = ""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            existing = f.read()
        shutil.copy(path, path + ".aci.bak")
    if remove:
        if block_header not in existing:
            return "was not connected"
        lines = existing.splitlines()
        out, skip = [], False
        for ln in lines:
            if ln.strip() == block_header:
                skip = True
                continue
            if skip and ln.startswith("[") and ln.strip() != block_header:
                skip = False
            if not skip:
                out.append(ln)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(out).strip() + "\n")
        return "disconnected"
    if block_header in existing:
        return "already connected"
    args = ", ".join('"%s"' % a.replace("\\", "\\\\") for a in _entry()["args"])
    block = (f'\n{block_header}\ncommand = "py"\nargs = [{args}]\n'
             f'env = {{ ACI_URL = "http://127.0.0.1:7077" }}\n')
    with open(path, "a", encoding="utf-8") as f:
        f.write(block)
    return "connected"


def run(remove=False):
    results = {}
    for name, path in _json_clients():
        try:
            results[name] = _merge_json(path, remove)
        except Exception as e:
            results[name] = f"error: {str(e)[:50]}"
    try:
        results["Codex CLI"] = _merge_codex(remove)
    except Exception as e:
        results["Codex CLI"] = f"error: {str(e)[:50]}"
    return results
