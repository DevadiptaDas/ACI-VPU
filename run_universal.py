"""
Universal connectivity demo - the proof that ACI is an open layer anything plugs
into, not an LLM tool.

Starts the ACI service, then connects FOUR heterogeneous clients to the SAME
service:
    1. a filesystem connector  (a data source - no AI)
    2. a CRM app               (an application - no AI)
    3. a shell/curl client     (any language - no AI)
    4. an AI client            (just one more consumer)

Then it shows all four sharing ONE cognitive brain (cross-source recall).

Run:  py run_universal.py        (optionally ACI_EMBEDDER=st)
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from clients.connector import ACIClient            # noqa: E402
from clients.filesystem_connector import ingest_dir  # noqa: E402
from clients import app_demo, llm_client            # noqa: E402

PORT = "7099"
URL = f"http://127.0.0.1:{PORT}"
DB = os.path.join(HERE, "_universal_demo.db")


def wait_health(timeout: float = 20.0) -> bool:
    for _ in range(int(timeout * 4)):
        try:
            urllib.request.urlopen(URL + "/health", timeout=1)
            return True
        except Exception:
            time.sleep(0.25)
    return False


def cleanup_db():
    for _ in range(5):
        try:
            if os.path.exists(DB):
                os.remove(DB)
            return
        except OSError:
            time.sleep(0.3)


def main():
    cleanup_db()
    env = {**os.environ, "ACI_PORT": PORT, "ACI_DB": DB,
           "ACI_EMBEDDER": os.environ.get("ACI_EMBEDDER", "lexical")}
    server = subprocess.Popen([sys.executable, os.path.join(HERE, "server", "aci_server.py")],
                              env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_health():
            print("ACI service failed to start.")
            return
        c = ACIClient(URL)
        print("=" * 72)
        print("  ONE ACI service. Four heterogeneous clients connecting over HTTP:")
        print("=" * 72)
        print(f"  health: {c.health()}")

        ing = ingest_dir(c, os.path.join(HERE, "sample_data"), full_resync=True)
        print(f"  1. [filesystem connector]  ingested {ing['files']} files / {ing['chunks']} chunks   (data source, no AI)")

        print(f"  2. [crm app]               stored {app_demo.run(c)} records           (app, no AI)")

        try:
            payload = json.dumps({
                "content": "Server room temperature threshold is 27C",
                "source_type": "SENSOR",
                "metadata": {"subject": "server room", "predicate": "temp threshold",
                             "object": "27C"}, "truth_value": 2.0})
            r = subprocess.run(["curl", "-s", "-XPOST", URL + "/monadise",
                                "-H", "Content-Type: application/json", "-d", payload],
                               capture_output=True, text=True, timeout=10)
            ok = r.returncode == 0 and r.stdout.strip().startswith("{")
            print(f"  3. [shell/curl client]     {'connected' if ok else 'curl missing - skipped'}            (any language)")
        except FileNotFoundError:
            print("  3. [shell/curl client]     curl not installed - skipped     (any HTTP language works)")

        print(f"  4. [ai client]             {llm_client.answer(c, 'who is acme primary contact?')[:46]}  (one more consumer)")

        print("\n  Cross-source recall - all four share ONE brain:")
        for q in ["acme contract renewal", "server room temperature", "company travel policy"]:
            hits = c.recall(q, k=1)
            if hits:
                print(f"    Q: {q:26} -> [{hits[0]['source_type']:6}] {hits[0]['summary'][:46]}")
            else:
                print(f"    Q: {q:26} -> (none)")

        print(f"\n  Combined state across all connectors: {c.compress()}")
        print("=" * 72)
        print("  Filesystem + app + shell + AI -> the SAME ACI. That's the substrate.")
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
        cleanup_db()


if __name__ == "__main__":
    main()
