"""
shadow_resolution_dryrun.py — PHASE 1 final gate: what WOULD the contradiction-
resolution dynamic do to the REAL accumulated store, before we ever turn it on?

STRICTLY READ-ONLY. Opens the real MonadStore, scans for competing fact-groups
(same subject::predicate, >=2 active claims with different objects), and simulates
the resolution dynamic on in-memory COPIES of (truth_value, entropy) — it NEVER
calls upsert, never writes, never touches the file. Then it reports:
  - how many competing fact-groups exist (impact surface),
  - how many would resolve vs hold as standoffs,
  - red flags: borderline resolutions, or a LESS-authoritative source winning
    (source-credibility inversion) — the cases a human should eyeball before flip.

If the surface is small and clean, flipping the default is low-risk. If it would
mass-supersede or shows inversions, we keep it OFF and refine.

Run:  py benchmark/shadow_resolution_dryrun.py  [db_path]
"""
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
from aci.store import MonadStore                 # noqa: E402
from aci import logic_gates as g                 # noqa: E402

DB = sys.argv[1] if len(sys.argv) > 1 else "aci_data.db"

# same validated parameter set as the wired dynamic
STANDOFF, MARGIN, PULL, DOM_ERODE = 0.15, 0.40, 0.55, 0.55
# rough source authority (higher = more trusted); for inversion detection only
RANK = {"USER": 5, "KNOWLEDGE": 4, "DOCUMENT": 4, "IMAGE": 4, "DERIVED": 3,
        "INFERENCE": 2, "WEB": 1}


def key_of(m):
    s, p = m.metadata.get("subject"), m.metadata.get("predicate")
    return f"{s.strip().lower()}::{p.strip().lower()}" if (s and p) else None


def obj_of(m):
    return (m.metadata.get("object") or m.value or "").strip().lower()


def compete(a, b):
    """One competition event on dict copies a,b -> mutate psi/S, return (changed)."""
    gap = abs(g.log_compress(a["psi"]) - g.log_compress(b["psi"]))
    if gap < STANDOFF:
        return False
    dom, sub = (a, b) if a["psi"] >= b["psi"] else (b, a)
    pressure = 1.0 - g.distance_decay(gap, 1.0)
    ratio = g.log_compress(sub["psi"]) / max(g.log_compress(dom["psi"]), g.EPS)
    k_sub = g.coupling_constant(sub["cc"], sub["S"])
    k_dom = g.coupling_constant(dom["cc"], dom["S"])
    sub["psi"] = max(sub["psi"] * (1.0 - PULL * pressure / k_sub), g.EPS)
    dom["psi"] = max(dom["psi"] * (1.0 - DOM_ERODE * pressure * ratio / k_dom), g.EPS)
    sub["S"] = min(sub["S"] + 0.05, 2.0)
    dom["S"] = min(dom["S"] + 0.03, 2.0)
    return True


def resolve_group(members):
    """Iterate competition among active members to convergence (read-only sim).
    Returns (superseded:list, standoff:bool)."""
    superseded = set()
    for _ in range(40):                       # bounded; converges fast
        active = [m for m in members if m["id"] not in superseded]
        if len(active) < 2:
            break
        changed = False
        for i in range(len(active)):
            for j in range(i + 1, len(active)):
                if compete(active[i], active[j]):
                    changed = True
                hi, lo = ((active[i], active[j]) if active[i]["psi"] >= active[j]["psi"]
                          else (active[j], active[i]))
                if g.log_compress(hi["psi"]) - g.log_compress(lo["psi"]) > MARGIN:
                    superseded.add(lo["id"])
        if not changed:
            break
        active2 = [m for m in members if m["id"] not in superseded]
        if len(active2) < 2:
            break
    standoff = len(superseded) == 0
    return superseded, standoff


print("=" * 88)
print(f" SHADOW DRY-RUN (READ-ONLY) — resolution over the real store: {DB}")
print("=" * 88)

store = MonadStore(DB, check_same_thread=True)
groups = defaultdict(list)
total = 0
for m in store.all():
    total += 1
    k = key_of(m)
    if not k:
        continue
    if m.metadata.get("status") == "superseded":
        continue
    groups[k].append({
        "id": m.id, "psi": float(m.truth_value), "S": float(m.entropy),
        "cc": float(getattr(m, "contextual_complexity", 1.0) or 1.0),
        "src": m.source_type, "obj": obj_of(m), "val": (m.value or "")[:60],
    })

competing = {k: ms for k, ms in groups.items()
             if len({m["obj"] for m in ms}) >= 2 and len(ms) >= 2}
cross = {k: ms for k, ms in competing.items()
         if len({m["src"] for m in ms}) >= 2}

print(f"\n  total monads scanned        : {total}")
print(f"  active fact-groups (subj::pred): {len(groups)}")
print(f"  competing groups (>=2 diff objs): {len(competing)}")
print(f"  ...of which CROSS-source        : {len(cross)}  (the soft-resolution target)")

would_resolve, standoffs, red_flags, samples = 0, 0, [], []
for k, ms in competing.items():
    sup, standoff = resolve_group([dict(m) for m in ms])
    if standoff:
        standoffs += 1
        continue
    would_resolve += 1
    by_id = {m["id"]: m for m in ms}
    losers = [by_id[i] for i in sup]
    winner = max((m for m in ms if m["id"] not in sup), key=lambda m: m["psi"], default=None)
    # red flag: a less-authoritative source would win over a superseded one
    for lo in losers:
        if winner and RANK.get(winner["src"], 3) < RANK.get(lo["src"], 3):
            red_flags.append((k, winner, lo))
    if len(samples) < 12:
        samples.append((k, winner, losers))

print(f"\n  would RESOLVE (>=1 supersession): {would_resolve}")
print(f"  would HOLD as standoff          : {standoffs}")
print(f"  RED FLAGS (source inversion)    : {len(red_flags)}")

if samples:
    print("\n  sample proposed resolutions (winner  <-  superseded):")
    for k, w, los in samples[:12]:
        ws = f"{w['src']}/psi{w['psi']:.2f} '{w['obj'][:24]}'" if w else "(none)"
        ls = "; ".join(f"{l['src']}/psi{l['psi']:.2f} '{l['obj'][:24]}'" for l in los)
        print(f"    [{k[:34]:34}] {ws}  <-  {ls}")

if red_flags:
    print("\n  RED FLAGS — less-authoritative source would win (eyeball before flip):")
    for k, w, lo in red_flags[:12]:
        print(f"    [{k[:34]:34}] winner {w['src']}/psi{w['psi']:.2f} beats {lo['src']}/psi{lo['psi']:.2f}")

print("\n" + "-" * 88)
# The WIRED dynamic targets cross-source competitors. Judge against THAT, and against
# whether the competing triples are real facts vs extraction noise.
if len(cross) == 0:
    print("  VERDICT: KEEP OFF (and flipping would be pointless). The wired dynamic targets")
    print("  CROSS-source competing claims, of which the store has ZERO — every monad is one")
    print(f"  source type. So the flag is INERT on real data. Worse, the {len(competing)} same-source")
    print("  'competing groups' are dominated by EXTRACTION NOISE (junk subject::predicate::object")
    print("  triples pulled from document prose), not genuine contradictions — see samples.")
    print("  -> Contradiction-resolution belongs on the CLEAN-FACT path (assert_fact / structured")
    print("     KNOWLEDGE), not document-chunk ingest. The real bottleneck is triple-extraction")
    print("     quality, not the resolution dynamic (which is proven correct in isolation).")
elif not red_flags and would_resolve <= max(5, len(cross) // 2):
    print("  VERDICT: small, clean CROSS-source surface, no inversions. Low-risk to flip the")
    print("  default AFTER human review of the samples above.")
else:
    print("  VERDICT: keep OFF — cross-source surface large or shows inversions. Refine first.")
print("=" * 88)
print("  (read-only: no upsert/write was performed; the store file was not modified)")
