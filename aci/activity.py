"""
Activity feed - the spine that makes ACI's work visible everywhere.

Every contribution ACI makes (recall served, claim grounded, page/file captured,
storage optimized) is recorded as a structured event. Each surface renders the same
feed its own way: an AI states "via ACI: recalled 3 of your notes", the Console/overlay
shows a live stream, the browser badge shows the page-relevant slice. Thread-safe,
in-memory ring buffer (recent activity is ephemeral); query via GET /activity.
"""
from __future__ import annotations
import threading
import time

KINDS = ("recall", "ground", "remember", "capture", "optimize")


class ActivityLog:
    def __init__(self, cap: int = 300):
        self.cap = cap
        self._events = []
        self._seq = 0
        self._lock = threading.Lock()

    def record(self, kind: str, summary: str, detail: dict = None) -> dict:
        with self._lock:
            self._seq += 1
            ev = {"seq": self._seq, "kind": kind, "summary": summary,
                  "detail": detail or {}, "ts": int(time.time() * 1000)}
            self._events.append(ev)
            if len(self._events) > self.cap:
                self._events.pop(0)
            return ev

    def recent(self, since: int = 0, limit: int = 50) -> list:
        with self._lock:
            evs = [e for e in self._events if e["seq"] > since]
            return evs[-limit:]

    def counts(self) -> dict:
        with self._lock:
            out = {k: 0 for k in KINDS}
            for e in self._events:
                out[e["kind"]] = out.get(e["kind"], 0) + 1
            out["total"] = self._seq
            return out
