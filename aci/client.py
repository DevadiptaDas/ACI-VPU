"""
ACIClient - the official Python SDK (stdlib urllib, ~50 lines).

Connecting any program to ACI is this small. Equivalent SDKs in JS/Kotlin/Go are
just as small - it's plain HTTP+JSON. JS SDK: clients/aci.js.
"""
from __future__ import annotations
import json
import urllib.request
from typing import Optional


class ACIClient:
    def __init__(self, base_url: str = "http://127.0.0.1:7077",
                 api_key: Optional[str] = None, timeout: float = 10.0):
        self.base = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: Optional[dict] = None) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    # cognition primitives
    def health(self) -> dict:
        return self._request("GET", "/health")

    def compress(self) -> dict:
        return self._request("GET", "/compress")

    def monadise(self, content: str, source_type: str = "DERIVED",
                 observer: Optional[str] = None, metadata: Optional[dict] = None,
                 truth_value: float = 1.0, summary: Optional[str] = None,
                 agent: Optional[str] = None) -> dict:
        return self._request("POST", "/monadise", {
            "content": content, "source_type": source_type, "observer": observer,
            "metadata": metadata or {}, "truth_value": truth_value, "summary": summary,
            "agent": agent})

    def recall(self, query: str, k: int = 5, observer: Optional[dict] = None,
               agent: Optional[str] = None, as_of: Optional[float] = None) -> list:
        # as_of (epoch seconds) = the Time Machine: reconstruct what was valid AT that
        # time. The service/core already support it; this just carries it through.
        return self._request("POST", "/recall",
                             {"query": query, "k": k, "observer": observer, "agent": agent,
                              "as_of": as_of})["hits"]

    def recall_images(self, query: str, k: int = 8) -> list:
        return self._request("POST", "/recall_images", {"query": query, "k": k})["images"]

    def validate(self, statement: str, metadata: Optional[dict] = None,
                 truth_value: Optional[float] = None, observer: Optional[dict] = None,
                 agent: Optional[str] = None) -> dict:
        return self._request("POST", "/validate", {
            "statement": statement, "metadata": metadata or {},
            "truth_value": truth_value, "observer": observer, "agent": agent})

    def relate(self, source_id: str, target_id: str, type: str = "ASSOCIATIVE") -> dict:
        return self._request("POST", "/relate",
                             {"source_id": source_id, "target_id": target_id, "type": type})

    def route(self, query: str) -> dict:
        return self._request("POST", "/route", {"query": query})

    # skill memory — a shared, self-curating skill library (declarative skills)
    def save_skill(self, name: str, intent: str, body: str, *,
                   args: Optional[list] = None, tags: Optional[list] = None,
                   author: Optional[str] = None, context: Optional[str] = None,
                   truth_value: float = 1.0) -> dict:
        return self._request("POST", "/save_skill", {
            "name": name, "intent": intent, "body": body, "args": args, "tags": tags,
            "author": author, "context": context, "truth_value": truth_value})

    def find_skills(self, intent: str, k: int = 5, context: Optional[str] = None) -> list:
        return self._request("POST", "/find_skills",
                             {"intent": intent, "k": k, "context": context})["skills"]

    def skill_outcome(self, skill_id: str, success: bool, weight: float = 1.0) -> dict:
        return self._request("POST", "/skill_outcome",
                             {"skill_id": skill_id, "success": success, "weight": weight})

    # admin / privacy
    def monads(self, limit: int = 50, source_type: Optional[str] = None) -> list:
        q = f"/monads?limit={limit}"
        if source_type:
            q += f"&source_type={source_type}"
        return self._request("GET", q)["monads"]

    def forget(self, monad_id: str) -> dict:
        return self._request("POST", "/forget", {"id": monad_id})

    def forget_by_source(self, path: str) -> dict:
        return self._request("POST", "/forget_by_source", {"path": path})

    # autonomy
    def ingest(self, path: str, full_resync: bool = False,
               agent: Optional[str] = None) -> dict:
        """Index a folder (recursive, incremental, policy-gated) into memory."""
        return self._request("POST", "/ingest",
                             {"path": path, "full_resync": full_resync, "agent": agent})

    def watch(self, path: str, defer: bool = False) -> dict:
        return self._request("POST", "/watch", {"path": path, "defer": defer})

    def unwatch(self, path: str) -> dict:
        return self._request("POST", "/unwatch", {"path": path})

    def watched(self) -> list:
        return self._request("GET", "/watched")["watched"]

    def stop(self) -> dict:
        return self._request("POST", "/shutdown", {})

    # privacy & control
    def policy(self) -> dict:
        return self._request("GET", "/policy")

    def pause(self, paused: bool = True) -> dict:
        return self._request("POST", "/pause", {"paused": paused})

    def consent(self, scope: str, allowed: bool = True, note: str = "") -> dict:
        return self._request("POST", "/consent",
                             {"scope": scope, "allowed": allowed, "note": note})

    # device optimization (USP-2)
    def device(self) -> dict:
        return self._request("GET", "/device")

    def scan_dupes(self, path: str, min_size: int = 1 << 20) -> dict:
        return self._request("POST", "/scan_dupes", {"path": path, "min_size": min_size})

    def clean(self, paths: list) -> dict:
        return self._request("POST", "/clean", {"paths": paths})

    # memory compressor (delete-safe archive)
    def archive(self, path: str) -> dict:
        return self._request("POST", "/archive", {"path": path})

    def restore(self, path: str, dest: str = None) -> dict:
        return self._request("POST", "/restore", {"path": path, "dest": dest})

    def archive_stats(self) -> dict:
        return self._request("GET", "/archive_stats")

    def delete_original(self, path: str) -> dict:
        return self._request("POST", "/delete_original", {"path": path})

    def graph(self) -> dict:
        return self._request("GET", "/graph")

    def activity(self, since: int = 0) -> dict:
        return self._request("GET", f"/activity?since={since}")

    # hardening
    def integrity(self) -> dict:
        return self._request("GET", "/integrity")

    def backup(self, path: str) -> dict:
        return self._request("POST", "/backup", {"path": path})

    def compact(self, purge_superseded: bool = False, older_than_days=None) -> dict:
        return self._request("POST", "/compact",
                             {"purge_superseded": purge_superseded, "older_than_days": older_than_days})

    def wipe(self, confirm: bool = False) -> dict:
        return self._request("POST", "/wipe", {"confirm": confirm})

    # phase D: observe-everything
    def observe(self, enabled: bool = True) -> dict:
        return self._request("POST", "/observe", {"enabled": enabled})

    def focused_text(self) -> dict:
        return self._request("GET", "/focused_text")

    def ocr_screen(self) -> dict:
        return self._request("POST", "/ocr_screen", {})

    def ingest_mail(self, host: str, user: str, password: str,
                    folder: str = "INBOX", limit: int = 50, port: int = 993) -> dict:
        return self._request("POST", "/ingest_mail", {
            "host": host, "user": user, "password": password,
            "folder": folder, "limit": limit, "port": port})
