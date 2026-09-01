"""
sim_monad_being.py — SIMULATION of the cognitive Monad Being.

A "Being" = a persistent identity + goals + accumulated experience (monads),
DECOUPLED from the "body" (the host/robot it runs on). Tests the core claim:

  "The body is replaceable; the experience and identity persist."

Tests:
  T1 identity persists                — the Being knows who it is
  T2 experience accumulates           — it learns from what its body perceives
  T3 BODY TRANSFER (headline)         — decommission body A, load Being into a NEW
                                        body B; experience learned on A survives
  T4 long-history continuity          — years of accumulated experience survive a
                                        model/body upgrade
  T5 goals persist across transfer
  T6 (Being + Mesh) fleet learning    — one Being's experience reaches another

This validates the COGNITIVE Being (identity + memory + continuity + transfer).
It does NOT validate the PHYSICAL body — sensors, actuators, real-time control,
perception, safety — which is the unbuilt robotics-hardware layer.

Run:  ACI_EMBEDDER=sentence-transformers py benchmark/sim_monad_being.py
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("ACI_EMBEDDER", "sentence-transformers")

from aci.aci import ACI                                    # noqa: E402
from aci.embeddings import get_default                     # noqa: E402

EMB = get_default()


class Being:
    """Identity + goals + memory, loadable into any host body. The memory lives on
    disk, so the Being survives the body being destroyed."""

    def __init__(self, being_id, name, goals, mem_path, body):
        self.id, self.name, self.goals = being_id, name, goals
        self.mem_path, self.body = mem_path, body
        self.aci = ACI(db_path=mem_path, observer_id=being_id, embedder=EMB)  # rehydrates from disk
        if not any(m.source_type == "IDENTITY" for m in self.aci.store.all()):
            self.aci.monadise(f"I am {name}, unit {being_id}. My goals: {goals}.",
                              source_type="IDENTITY", metadata={"kind": "identity"})

    def perceive(self, observation):                       # the body feeds experience
        self.aci.monadise(observation, source_type="EXPERIENCE",
                          metadata={"learned_on_body": self.body})

    def act(self, question):                               # recall experience to decide
        return [h.monad.value for h in self.aci.recall(question, k=3)]

    def decommission(self):                                # body destroyed; memory persists to disk
        self.aci.close()


def transfer(old, new_body):
    """Move the Being into a new body: destroy old host, load identity+memory into new."""
    being_id, name, goals, path = old.id, old.name, old.goals, old.mem_path
    old.decommission()
    return Being(being_id, name, goals, path, body=new_body)


results = []
def check(name, ok, detail=""):
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


print("=" * 80)
print(" MONAD BEING SIMULATION — cognitive identity + experience continuity")
print("=" * 80)

mem = tempfile.mktemp(suffix=".db")
unit = Being("U-27", "Atlas-27", "keep the warehouse running safely", mem, body="ChassisV1")

# --- life on body A (ChassisV1) ---
print("\nLife on body A (ChassisV1): accumulating experience...")
unit.perceive("Drawer type A opens by pulling the handle firmly, not sliding.")
unit.perceive("Machine M7 jams when the input bin is overloaded past the red line.")
unit.perceive("Operator Priya works the morning shift and handles fragile crates.")
unit.perceive("On 2023-04-02 the loader failed because bearing B12 overheated.")
for _ in range(3):   # simulate years of routine experience
    unit.perceive("Routine pallet move on aisle 5 completed without incident.")

# T1 identity
ident = unit.act("who am I and what are my goals")
check("T1 identity persists", any("atlas-27" in r.lower() for r in ident),
      f"recalled='{(ident[0] if ident else '')[:50]}'")

# T2 experience accumulates + is usable
ans = unit.act("how do I open a type A drawer?")
check("T2 experience accumulates & is recallable",
      any("pulling the handle" in r.lower() for r in ans), f"recalled='{(ans[0] if ans else '')[:50]}'")

# --- THE HEADLINE: transfer to a brand-new body ---
print("\nBody A decommissioned. New body B (ChassisV2) arrives. Transferring Being...")
unit = transfer(unit, new_body="ChassisV2")

# T3 experience learned on body A survives on body B
a3 = unit.act("how do I open a type A drawer?")
survived = any("pulling the handle" in r.lower() for r in a3)
# and it knows WHERE it learned it (on the old body)
prov = unit.aci.recall("type A drawer", k=1)
prov_body = (prov[0].monad.metadata.get("learned_on_body") if prov else None)
check("T3 BODY TRANSFER: experience survives the new body", survived,
      f"recalled on ChassisV2='{(a3[0] if a3 else '')[:45]}', learned_on={prov_body}")

# T4 long-history continuity (a past failure learned on body A, recalled on body B)
a4 = unit.act("what caused the loader failure?")
check("T4 long-history continuity survives upgrade",
      any("bearing b12" in r.lower() or "overheat" in r.lower() for r in a4),
      f"recalled='{(a4[0] if a4 else '')[:50]}'")

# T5 goals persist across transfer
a5 = unit.act("what are my goals")
check("T5 goals persist across body change",
      any("warehouse" in r.lower() for r in a5), f"recalled='{(a5[0] if a5 else '')[:45]}'")

# T6 Being + Mesh: a second Being gains the first's experience (fleet learning)
print("\nFleet: a SECOND being (U-42, fresh body) learns from U-27 via shared memory...")
mem2 = tempfile.mktemp(suffix=".db")
unit2 = Being("U-42", "Atlas-42", "keep the warehouse running safely", mem2, body="ChassisV2")
before = any("pulling the handle" in r.lower() for r in unit2.act("how do I open a type A drawer?"))
# mesh sync: copy U-27's EXPERIENCE monads into U-42 (federation)
for m in unit.aci.store.all():
    if m.source_type == "EXPERIENCE":
        unit2.aci.monadise(m.value, source_type="EXPERIENCE", metadata=dict(m.metadata))
after = any("pulling the handle" in r.lower() for r in unit2.act("how do I open a type A drawer?"))
check("T6 fleet learning: a fresh being gains another's experience",
      (not before) and after, f"before={before}, after={after}")

print("\n" + "-" * 80)
p = sum(results)
print(f"  RESULT: {p}/{len(results)} cognitive-Being tests passed")
print("  NOTE: validates identity + memory + experience-continuity + body-transfer")
print("  at the COGNITIVE/data level. Does NOT validate the PHYSICAL body —")
print("  sensors, actuators, real-time control, perception, safety — which is the")
print("  unbuilt robotics-hardware layer and the genuinely hard part.")
print("=" * 80)
