"""
Tier + connection cap.

The free tier allows up to 3 connected AIs; a Pro/Team license lifts the cap.
Enforcement is a SOFT gate — it bounds the honest majority and creates the upgrade
prompt; it is not DRM (local software can't be, and we don't pretend otherwise).

Only self-identifying AI connections (callers that pass an `agent` id — e.g. the MCP
bridge naming the connecting AI) count against the cap. The user's own device,
Console, file-watcher, and SDK-without-agent usage is NEVER capped or counted.

Tier is read from the ACI_LICENSE env var (or a license file the caller loads):
  ""/"free"/"community"  -> free   (cap 3)
  "pro..."/"enterprise"/"unlimited"/any-other-key -> pro  (unlimited)
  "team..."             -> team   (unlimited; seat-billed out-of-band)
"""
from __future__ import annotations
import json
import os
from typing import Iterable, Optional

FREE_MAX_CONNECTIONS = 3


def resolve_tier(key: Optional[str] = None) -> str:
    key = (key if key is not None else os.environ.get("ACI_LICENSE", "")).strip().lower()
    if not key or key in ("free", "community"):
        return "free"
    if key.startswith("team"):
        return "team"
    return "pro"                       # pro / enterprise / unlimited / any issued key


def cap_for(tier: str) -> Optional[int]:
    return FREE_MAX_CONNECTIONS if tier == "free" else None   # None = unlimited


class ConnectionGate:
    """Counts DISTINCT connected AI agents; denies a NEW one once the free cap is hit."""

    def __init__(self, tier: str = "free", known: Optional[Iterable[str]] = None):
        self.tier = tier
        self.cap = cap_for(tier)
        self.known = set(known or ())

    def check(self, agent: Optional[str]) -> dict:
        if not agent:                                  # user's own device/console/SDK
            return {"allowed": True, "counted": False, "tier": self.tier,
                    "connections": len(self.known), "cap": self.cap}
        agent = str(agent).strip().lower()
        if agent in self.known:
            allowed, counted = True, False
        elif self.cap is not None and len(self.known) >= self.cap:
            allowed, counted = False, False
        else:
            allowed, counted = True, True
            self.known.add(agent)
        out = {"allowed": allowed, "counted": counted, "tier": self.tier,
               "agent": agent, "connections": len(self.known), "cap": self.cap}
        if not allowed:
            out["upgrade"] = (f"Free tier is capped at {self.cap} connected AIs. "
                              "Upgrade to Pro for unlimited AI connections.")
        return out


def load_known(path: str) -> set:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_known(path: str, known: Iterable[str]) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sorted(known), f)
    except Exception:
        pass
