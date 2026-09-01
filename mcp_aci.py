"""Launcher so the ACI MCP server runs from any working directory.

Used by .mcp.json / `claude mcp add` with an absolute path, so the AI host can
start it regardless of where it was launched from.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aci.mcp_server import main  # noqa: E402

if __name__ == "__main__":
    main()
