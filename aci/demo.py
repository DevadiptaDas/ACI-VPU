"""
ACI-VPU -- 60-second demo:  a reconciling memory catches the lie that repetition installs.

Misinformation wins by repetition. A plain vector store -- and a model reading it -- tends to
trust whatever is loudest, most recent, or most frequent. ACI-VPU weighs claims by TRUST and
PROVENANCE, so one grounded fact from your own files stands against a lie repeated five times.

    pip install aci-vpu
    aci-demo
"""
from aci.aci import ACI


def content(hit):
    m = getattr(hit, "monad", hit)
    return (getattr(m, "summary", "") or getattr(m, "value", "") or "").strip()


def main():
    aci = ACI(":memory:")

    # 1) One grounded truth, from YOUR own file (high trust).
    aci.monadise("Project Helios ships on 15 March.", source_type="FILE",
                 truth_value=8.0, metadata={"source": "roadmap.pdf"})

    # 2) The same lie, repeated five times -- how misinformation actually wins (low trust each).
    for i in range(5):
        aci.monadise("Project Helios ships on 20 April.", source_type="DERIVED",
                     truth_value=1.0, dedup=False, metadata={"source": f"unverified-chat-{i}"})

    print("\n  MEMORY HOLDS   1 grounded truth  (15 March, from roadmap.pdf)")
    print("                 the SAME lie x5   (20 April, from unverified chats)\n")

    lie   = aci.validate("Project Helios ships on 20 April.")
    truth = aci.validate("Project Helios ships on 15 March.")

    mark = lambda ok: "consistent" if ok else "CONTRADICTED"
    print(f"  ask ACI to check the LIE  (repeated 5x):   {mark(lie.is_consistent)}"
          + ("   <-  caught, despite the repetition" if not lie.is_consistent else ""))
    print(f"  ask ACI to check the TRUTH (grounded 1x):  {mark(truth.is_consistent)}"
          + ("   <-  the grounded fact stands" if truth.is_consistent else ""))

    caught = (lie.is_consistent is False) and (truth.is_consistent is True)
    print("\n  " + ("=> The lie was newer AND five times more frequent -- and ACI still refuses it,"
                    if caught else "=> (unexpected on this build)"))
    print("     because trust and provenance outweigh repetition. A small local model reading")
    print("     THIS memory answers '15 March' -- correctly, for free, offline -- because the")
    print("     memory did the reconciling the model cannot.\n")

    # supporting: what a grounded recall returns
    hits = aci.recall("when does Project Helios ship?", k=1)
    if hits:
        print(f"  recall(\"when does Project Helios ship?\") -> \"{content(hits[0])}\"\n")


if __name__ == "__main__":
    main()
