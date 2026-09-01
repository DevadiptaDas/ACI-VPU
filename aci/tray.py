"""
ACI desktop HUD / control panel (Phase 4 + integration).

A small always-available window so a normal user runs ACI without a terminal and
*sees* what it's doing. Stdlib tkinter only (no dependency). Shows:
  - live status (running / monads / encrypted / paused / observing)
  - device health + optimization (on demand)
  - a recall box (search your memory by meaning)
  - the live ACI activity feed (what ACI is doing for you, refreshing)
and one-click Console / Pause / Observe / Stop. Auto-starts the service on launch.

    py -m aci.cli tray        (or: pythonw -m aci.cli tray  for no console window)

A global-hotkey "summon" overlay needs an optional dep; this stdlib panel gives the
same surface without one.
"""
from __future__ import annotations
import os
import subprocess
import sys


def _bh(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"


def main():
    import tkinter as tk
    from aci.client import ACIClient

    url = os.environ.get("ACI_URL", "http://127.0.0.1:7077")
    key = os.environ.get("ACI_API_KEY") or None
    c = ACIClient(url, api_key=key)

    def health():
        try:
            return c.health()
        except Exception:
            return None

    def ensure_running():
        if health() is None:
            subprocess.Popen([sys.executable, "-m", "aci.cli", "serve"], env={**os.environ},
                             creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))

    root = tk.Tk()
    root.title("ACI")
    root.geometry("440x580")
    F = ("Segoe UI", 10)
    tk.Label(root, text="ACI - cognition layer", font=("Segoe UI", 13, "bold")).pack(pady=(10, 0))
    statusv = tk.StringVar(value="starting...")
    tk.Label(root, textvariable=statusv, font=F, fg="#333").pack(pady=2)

    # --- device health ---
    hf = tk.LabelFrame(root, text="Device", font=F)
    hf.pack(fill="x", padx=10, pady=4)
    healthv = tk.StringVar(value="(click Refresh health)")
    tk.Label(hf, textvariable=healthv, font=("Consolas", 9), justify="left", anchor="w").pack(fill="x", padx=6)

    def load_health():
        healthv.set("reading...")
        try:
            d = c.device()
            lines = [f"{x['mount']} {x['percent_used']}% used, {_bh(x['free'])} free" for x in d.get("disks", [])]
            if d.get("memory"):
                lines.append(f"RAM {d['memory']['percent_used']}% used")
            if d.get("battery"):
                b = d["battery"]
                lines.append(f"battery {b['percent']}%" + (f", health {b.get('health_percent')}%" if b.get("health_percent") else ""))
            if d.get("cpu"):
                lines.append(f"CPU {d['cpu']['load_percent']}%")
            lines += ["- " + r for r in d.get("recommendations", [])[:2]]
            healthv.set("\n".join(lines) or "(no data)")
        except Exception:
            healthv.set("(service not running)")
    tk.Button(hf, text="Refresh health", font=F, command=load_health).pack(anchor="e", padx=6, pady=3)

    # --- recall ---
    rf = tk.LabelFrame(root, text="Recall your memory", font=F)
    rf.pack(fill="x", padx=10, pady=4)
    qv = tk.StringVar()
    row = tk.Frame(rf)
    row.pack(fill="x", padx=6, pady=3)
    ent = tk.Entry(row, textvariable=qv, font=F)
    ent.pack(side="left", fill="x", expand=True)
    rtext = tk.Text(rf, height=5, font=("Consolas", 9), wrap="word")
    rtext.pack(fill="x", padx=6, pady=3)

    def do_recall(*_):
        rtext.delete("1.0", "end")
        try:
            hits = c.recall(qv.get(), k=5)
        except Exception:
            rtext.insert("end", "(service not running)")
            return
        if not hits:
            rtext.insert("end", "no matches")
            return
        for h in hits:
            rtext.insert("end", f"- {(h.get('summary') or h.get('value') or '')[:90]}\n")
    tk.Button(row, text="Recall", font=F, command=do_recall).pack(side="right", padx=(6, 0))
    ent.bind("<Return>", do_recall)

    # --- activity feed ---
    af = tk.LabelFrame(root, text="ACI activity (live)", font=F)
    af.pack(fill="both", expand=True, padx=10, pady=4)
    feed = tk.Text(af, height=9, font=("Consolas", 9), wrap="word", state="disabled")
    feed.pack(fill="both", expand=True, padx=6, pady=4)

    # --- buttons ---
    bf = tk.Frame(root)
    bf.pack(pady=6)

    def act(fn):
        try:
            fn()
        except Exception:
            pass

    def toggle_pause():
        h = health()
        if h:
            act(lambda: c.pause(not h.get("paused")))

    def toggle_observe():
        h = health()
        if h:
            act(lambda: c.observe(not h.get("observing")))

    import webbrowser
    tk.Button(bf, text="Console", font=F, width=9, command=lambda: webbrowser.open(url + "/console")).grid(row=0, column=0, padx=3)
    tk.Button(bf, text="Pause/Resume", font=F, width=12, command=toggle_pause).grid(row=0, column=1, padx=3)
    tk.Button(bf, text="Observe", font=F, width=9, command=toggle_observe).grid(row=0, column=2, padx=3)
    tk.Button(bf, text="Stop", font=F, width=6, command=lambda: act(c.stop)).grid(row=0, column=3, padx=3)
    tk.Button(root, text="Quit (leave ACI running)", font=F, command=root.destroy).pack(pady=(0, 8))

    def refresh_status():
        h = health()
        if h:
            bits = [f"{h.get('monads', 0)} monads",
                    "encrypted" if h.get("encrypted") else "not encrypted"]
            if h.get("paused"):
                bits.append("PAUSED")
            if h.get("observing"):
                bits.append("observing")
            statusv.set("running - " + " - ".join(bits))
        else:
            statusv.set("not running")
        root.after(3000, refresh_status)

    def refresh_feed():
        try:
            evs = c.activity().get("events", [])
        except Exception:
            evs = []
        feed.config(state="normal")
        feed.delete("1.0", "end")
        for e in evs[-14:][::-1]:
            feed.insert("end", f"[{e['kind']}] {e['summary']}\n")
        feed.config(state="disabled")
        root.after(4000, refresh_feed)

    ensure_running()
    root.after(700, refresh_status)
    root.after(1000, refresh_feed)
    root.mainloop()


if __name__ == "__main__":
    main()
