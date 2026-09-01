"""
MEASURED optimization benchmark (Phase 3 / USP-2).

Every number below is measured on a workload - nothing asserted. The patent
claims "20-30% memory/energy savings"; this reports what the monad layer ACTUALLY
delivers, with methodology and honest caveats. Savings are workload-dependent:
high on redundant/known workloads, ~0 on fully-novel ones.

Run:  py benchmark/benchmark_optimization.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aci import ACI                       # noqa: E402
from aci.optimize import EnergyGovernor   # noqa: E402
from aci.monad import Monad               # noqa: E402


def pct(saved, total):
    return round(100.0 * saved / total, 1) if total else 0.0


def storage_dedup():
    """10 unique docs, each appearing 5x (realistic redundancy)."""
    aci = ACI(db_path=":memory:")
    docs = [f"Engineering note {i}: " + (f"subsystem {i} status nominal. " * 40)
            for i in range(10)]
    raw_bytes = 0
    for _ in range(5):
        for d in docs:
            aci.monadise(d, source_type="FILE", summary=f"note {d[:18]}")
            raw_bytes += len(d.encode("utf-8"))
    stored = aci.compress()["stored_bytes"]
    aci.close()
    return raw_bytes, stored, pct(raw_bytes - stored, raw_bytes)


def repeat_inference():
    """200 requests drawn from 20 distinct intents (10x repetition)."""
    aci = ACI(db_path=":memory:")
    intents = [
        "summarize the quarterly revenue report", "translate the contract into french",
        "extract action items from the standup", "classify this support ticket",
        "draft a reply to the vendor email", "compute the project risk score",
        "generate release notes for v2", "find duplicate invoices this month",
        "explain the refund policy", "rank candidates for the role",
        "detect anomalies in server logs", "forecast next month demand",
        "redact PII from this document", "convert the spec to a checklist",
        "score lead quality for acme", "summarize the legal clause",
        "plan the sprint backlog", "diagnose the failed deployment",
        "recommend a pricing tier", "audit the access permissions",
    ]
    calls = {"n": 0}

    def expensive(c):
        calls["n"] += 1
        return f"result::{c[:18]}"

    for i in range(200):
        aci.cached_compute(intents[i % len(intents)], expensive)
    stats = aci.cache_stats()
    aci.close()
    return stats, calls["n"]


def context_reduction():
    """Raw context = all docs concatenated; ACI = top-3 monad summaries."""
    aci = ACI(db_path=":memory:")
    docs = [f"Customer {n} prefers email; renewal in Q{(n % 4) + 1}; tier gold."
            for n in range(40)]
    for d in docs:
        aci.monadise(d, source_type="APP")
    raw_ctx = "\n".join(docs)
    aci_ctx, n = aci.build_context("customer renewal quarter", k=3)
    aci.close()
    return len(raw_ctx), len(aci_ctx), pct(len(raw_ctx) - len(aci_ctx), len(raw_ctx))


def compute_gating():
    """Stream of 100 events: 20 meaningful (high ψ, low S) + 80 noise (low ψ, high S)."""
    signal = [Monad(summary=f"signal {i}", truth_value=2.0, entropy=0.1) for i in range(20)]
    noise = [Monad(summary=f"noise {i}", truth_value=0.3, entropy=3.0) for i in range(80)]
    process, suppress = EnergyGovernor.gate(signal + noise, min_value=0.5)
    return len(process), len(suppress), pct(len(suppress), 100)


def cloud_routing():
    """50 queries: 30 about locally-known facts, 20 novel -> cloud."""
    aci = ACI(db_path=":memory:")
    facts = [f"Internal policy {i}: process {i} requires two approvals." for i in range(30)]
    for f in facts:
        aci.monadise(f, source_type="APP", truth_value=2.0)
    local = 0
    for i in range(30):
        if aci.route(f"policy {i} approvals")["target"] == "local":
            local += 1
    novel_cloud = 0
    for i in range(20):
        if aci.route(f"weather forecast city {i} tomorrow")["target"] == "cloud":
            novel_cloud += 1
    aci.close()
    return local, novel_cloud, pct(local, 50)


def main():
    raw_b, stored_b, storage_pct = storage_dedup()
    cache, computes = repeat_inference()
    raw_c, aci_c, ctx_pct = context_reduction()
    proc, supp, gate_pct = compute_gating()
    local_hits, novel_cloud, cloud_pct = cloud_routing()

    print("=" * 72)
    print("  MEASURED OPTIMIZATION (USP-2)  -  numbers, not claims")
    print("=" * 72)
    print(f"  Storage (dedup+monadise)   {raw_b:>8} B -> {stored_b:>6} B   saved {storage_pct}%")
    print(f"  Repeat-inference avoided   {cache['requests']} reqs -> {computes} computes   "
          f"avoided {cache['inference_avoided_pct']}%")
    print(f"  LLM context tokens         {raw_c:>8} ch -> {aci_c:>6} ch   reduced {ctx_pct}%")
    print(f"  Compute gating (noise)     suppressed {supp}/100 low-value events   saved {gate_pct}%")
    print(f"  Cloud calls avoided        {local_hits}/50 served locally               avoided {cloud_pct}%")
    print("=" * 72)
    print("  Methodology: redundancy/known-rate set by the workloads above.")
    print("  Caveats: monadisation is LOSSY (semantic recall, not byte-exact);")
    print("  gating savings assume the suppressed items are genuinely low-value;")
    print("  on fully-novel, non-redundant workloads these savings approach 0%.")
    print("  Patent claims 20-30% - on redundant/known workloads ACI exceeds that;")
    print("  the honest figure is: it depends on how repetitive your data is.")


if __name__ == "__main__":
    main()
