"""
ACI - one-command launcher for the finished MVP.

Starts the local ACI service (private, on-device, NO cloud) and opens the
Console in your browser. Then, in the Console:
  1. Paste a folder path into "Ingest folder" -> Ingest  (txt / md / PDF / Word)
  2. Search by meaning, Check statements for contradictions, toggle observer,
     see storage savings, forget anything.

    py quickstart.py

First run downloads the local models once (semantic embeddings + spaCy), then
cached. Your data persists locally in aci_data.db. Ctrl+C to stop.
"""
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PORT = os.environ.get("ACI_PORT", "7077")
URL = f"http://127.0.0.1:{PORT}"
DB = os.environ.get("ACI_DB", os.path.join(HERE, "aci_data.db"))


def wait_up(timeout: float = 90.0) -> bool:
    for _ in range(int(timeout * 2)):
        try:
            urllib.request.urlopen(URL + "/console", timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def main():
    env = {**os.environ, "ACI_PORT": PORT, "ACI_DB": DB, "ACI_HOST": "127.0.0.1"}
    print("Starting ACI (first run downloads the local models once, then cached)...")
    srv = subprocess.Popen([sys.executable, "-m", "aci.cli", "serve"], env=env)
    try:
        if not wait_up():
            print("ACI service did not start.")
            return
        try:
            import sentence_transformers  # noqa: F401
            mode = "semantic memory (full experience)"
        except Exception:
            mode = "lexical fallback (lite) - re-run install.ps1 and choose FULL for semantic memory"
        print("\n" + "=" * 66)
        print("  ACI is running locally - private, on-device, no cloud.")
        print(f"  Mode:     {mode}")
        print(f"  Console:  {URL}/console")
        print("  In the Console:")
        print("   1. Paste a folder path into 'Ingest folder' -> Ingest")
        print("      (your docs / notes - txt, md, PDF, Word)")
        print("   2. Search by meaning | Check statements for contradictions |")
        print("      toggle observer | see storage savings | forget anything")
        print(f"  Your data persists locally in: {DB}")
        print("  Ctrl+C to stop.")
        print("=" * 66 + "\n")
        try:
            webbrowser.open(f"{URL}/console")
        except Exception:
            pass
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nstopping...")
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except subprocess.TimeoutExpired:
            srv.kill()


if __name__ == "__main__":
    main()
