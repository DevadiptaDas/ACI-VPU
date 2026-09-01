"""
ACI launcher (#3) - a spotlight-style search bar over everything ACI knows.

A small always-on-top window: type a query, get semantic results across your files,
web, notes (text) AND your photos (CLIP), instantly. Stdlib tkinter, no dependency.

    py -m aci.cli search

Global-hotkey summon (no dependency): create a desktop shortcut to
`pythonw -m aci.cli search`, open its Properties, and set a "Shortcut key" (e.g.
Ctrl+Alt+Space). Windows then opens the launcher on that hotkey from anywhere.
"""
from __future__ import annotations
import os


def main(initial: str = ""):
    import tkinter as tk
    from aci.client import ACIClient

    url = os.environ.get("ACI_URL", "http://127.0.0.1:7077")
    key = os.environ.get("ACI_API_KEY") or None
    c = ACIClient(url, api_key=key)

    root = tk.Tk()
    root.title("ACI Search")
    root.attributes("-topmost", True)
    w, h = 600, 440
    root.geometry(f"{w}x{h}+{(root.winfo_screenwidth() - w) // 2}+200")

    qv = tk.StringVar(value=initial)
    ent = tk.Entry(root, textvariable=qv, font=("Segoe UI", 16))
    ent.pack(fill="x", padx=12, pady=12)
    ent.focus_set()
    ent.icursor("end")

    out = tk.Text(root, font=("Consolas", 10), wrap="word")
    out.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def search(*_):
        q = qv.get().strip()
        out.delete("1.0", "end")
        if not q:
            return
        try:
            hits = c.recall(q, k=8)
        except Exception:
            out.insert("end", "ACI service not running (start it: py quickstart.py)")
            return
        if hits:
            out.insert("end", "— memory —\n")
            for hh in hits:
                out.insert("end", f"  [{hh.get('source_type','?')}] "
                           f"{(hh.get('summary') or hh.get('value') or '')[:90]}\n")
        try:
            ims = c.recall_images(q, k=5)
        except Exception:
            ims = []
        if ims:
            out.insert("end", "\n— photos —\n")
            for im in ims:
                out.insert("end", f"  {im.get('score')}  {im.get('path')}\n")
        if not hits and not ims:
            out.insert("end", "no matches")

    ent.bind("<Return>", search)
    root.bind("<Escape>", lambda e: root.destroy())
    if initial:
        root.after(200, search)
    root.mainloop()


if __name__ == "__main__":
    import sys
    main(" ".join(sys.argv[1:]))
