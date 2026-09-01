"""
AI client - the LLM is just ONE more consumer of ACI, not special.

It recalls grounding from ACI before answering. The same service the filesystem
connector, the CRM app, and the shell client use.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clients.connector import ACIClient  # noqa: E402


def answer(client: ACIClient, question: str) -> str:
    hits = client.recall(question, k=3)
    memory = "; ".join(h["summary"] for h in hits) or "(nothing in ACI)"
    # a real LLM call would go here; we just show the grounding ACI provided
    return f"grounded on ACI memory -> {memory}"


if __name__ == "__main__":
    c = ACIClient(os.environ.get("ACI_URL", "http://127.0.0.1:7077"))
    print("[ai client]", answer(c, "who is acme's primary contact?"))
