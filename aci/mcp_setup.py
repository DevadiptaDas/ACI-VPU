"""
Portable MCP setup — register the ACI memory server with an MCP host (Claude Desktop,
Cursor, or any client), on any machine, with NO hardcoded paths.

The old `.mcp.json` pinned an absolute dev path. This generates the right
config for wherever ACI is actually installed: it prefers the installed `aci-mcp`
console command, and falls back to `<this python> -m aci.mcp_server`. It MERGES into an
existing config (never clobbers other servers) and backs the file up first.

Usage:
    aci-mcp-setup                     # write config for every detected client
    aci-mcp-setup --client claude     # just Claude Desktop
    aci-mcp-setup --client cursor      # just Cursor
    aci-mcp-setup --print              # print the snippet, write nothing
    aci-mcp-setup --url http://127.0.0.1:7077   # custom ACI URL
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import sys

SERVER_KEY = "aci"


def server_entry(url: str) -> dict:
    """The command the MCP host should run to launch the ACI server — portable.
    Prefer the installed console script; else the current interpreter + module."""
    exe = shutil.which("aci-mcp")
    if exe:
        entry = {"command": exe, "args": []}
    else:
        entry = {"command": sys.executable, "args": ["-m", "aci.mcp_server"]}
    entry["env"] = {"ACI_URL": url}
    return entry


def _claude_config_path() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(base, "Claude", "claude_desktop_config.json")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Claude/claude_desktop_config.json")
    return os.path.expanduser("~/.config/Claude/claude_desktop_config.json")


def _cursor_config_path() -> str:
    return os.path.expanduser("~/.cursor/mcp.json")


CLIENTS = {"claude": _claude_config_path, "cursor": _cursor_config_path}


def _merge_into(path: str, entry: dict) -> bool:
    """Add/replace mcpServers['aci'] in the JSON at `path`, preserving everything else.
    Creates the file/dirs if missing, backs up an existing file. Returns True on write."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            data = {}
        try:                                            # keep a one-shot backup
            shutil.copyfile(path, path + ".aios.bak")
        except Exception:
            pass
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    servers[SERVER_KEY] = entry
    data["mcpServers"] = servers
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="aci-mcp-setup",
                                 description="Register the ACI memory MCP server with your AI client(s).")
    ap.add_argument("--client", choices=["claude", "cursor", "both", "all"], default="all",
                    help="which MCP host to configure (default: all detected)")
    ap.add_argument("--url", default=os.environ.get("ACI_URL", "http://127.0.0.1:7077"),
                    help="ACI service URL the server should talk to")
    ap.add_argument("--print", dest="print_only", action="store_true",
                    help="print the config snippet and exit (write nothing)")
    a = ap.parse_args(argv)

    entry = server_entry(a.url)
    snippet = {"mcpServers": {SERVER_KEY: entry}}
    if a.print_only:
        print(json.dumps(snippet, indent=2))
        return 0

    targets = ["claude", "cursor"] if a.client in ("both", "all") else [a.client]
    wrote = 0
    for name in targets:
        path = CLIENTS[name]()
        try:
            _merge_into(path, entry)
            print(f"[ok]   {name:7} -> {path}")
            wrote += 1
        except Exception as e:
            print(f"[fail] {name:7} -> {path}  ({e})", file=sys.stderr)
    cmd = entry["command"] + (" " + " ".join(entry["args"]) if entry["args"] else "")
    print(f"\nACI MCP server command: {cmd}")
    print(f"Talking to ACI at:      {a.url}")
    if wrote:
        print("\nDone. Restart your AI client, then it will have the ACI memory tools "
              "(aci_recall, aci_remember, ...). Make sure the ACI service is running: `aci serve`.")
    else:
        print("\nNothing written. Use --print to see the snippet to paste manually.")
    return 0 if wrote or a.print_only else 1


if __name__ == "__main__":
    raise SystemExit(main())
