"""
A plain CRM app - a NON-AI application plugging into ACI.

It just stores and looks up customer facts. By going through ACI it gets memory,
semantic recall, and contradiction-checking for free, without being an AI app.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clients.connector import ACIClient  # noqa: E402

RECORDS = [
    ("Customer Acme prefers contact by email.",
     {"subject": "acme", "predicate": "contact preference", "object": "email"}),
    ("Acme contract renews on December 1.",
     {"subject": "acme", "predicate": "contract renewal", "object": "December 1"}),
    ("Acme primary contact is Rita Gomez.",
     {"subject": "acme", "predicate": "primary contact", "object": "Rita Gomez"}),
]


def run(client: ACIClient) -> int:
    for text, meta in RECORDS:
        client.monadise(text, source_type="APP", metadata=meta, truth_value=2.0)
    return len(RECORDS)


if __name__ == "__main__":
    c = ACIClient(os.environ.get("ACI_URL", "http://127.0.0.1:7077"))
    print(f"[crm app] stored {run(c)} records in ACI")
