"""
ACI command-line interface.

After `pip install -e .` you get an `aci` command. Without install:
    py -m aci.cli serve
    py -m aci.cli monadise "My accountant is Sarah Chen."
    py -m aci.cli recall "accountant"
    py -m aci.cli stats
    py -m aci.cli monads --limit 10
    py -m aci.cli forget <id>
"""
import argparse
import json
import os
import sys


def _client_args(sp):
    sp.add_argument("--url", default="http://127.0.0.1:7077")
    sp.add_argument("--key", default=None)


def _startup_bat():
    """Path to the per-user Windows Startup launcher (no admin needed)."""
    appdata = os.environ.get("APPDATA", "")
    return os.path.join(appdata, "Microsoft", "Windows", "Start Menu",
                        "Programs", "Startup", "ACI.bat")


def _do_autostart(remove=False):
    """Install/remove a login launcher so ACI runs on its own, hidden, on boot."""
    if os.name != "nt":
        print("autostart currently supports Windows; on macOS/Linux use launchd/systemd.")
        return 1
    bat = _startup_bat()
    if remove:
        if os.path.exists(bat):
            os.remove(bat)
            print(f"autostart removed ({bat}). ACI will no longer start on login.")
        else:
            print("autostart was not set.")
        return 0
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pyw = sys.executable.replace("python.exe", "pythonw.exe")  # windowless
    if not os.path.exists(pyw):
        pyw = sys.executable  # fall back (a console window may appear)
    content = (
        "@echo off\r\n"
        f'cd /d "{repo}"\r\n'
        "set ACI_DB=aci_data.db\r\n"
        f'start "" "{pyw}" -m aci.cli serve\r\n'
    )
    os.makedirs(os.path.dirname(bat), exist_ok=True)
    with open(bat, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"autostart installed: {bat}")
    print("ACI will now start automatically (hidden) every time you log in.")
    print("Stored in aci_data.db in the project folder. Undo with: aci autostart --remove")
    return 0


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _do_update():
    import subprocess
    repo = _repo_root()
    if os.path.isdir(os.path.join(repo, ".git")):
        print("updating via git pull...")
        subprocess.run(["git", "-C", repo, "pull"])
    else:
        print("reinstalling package...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-e", repo, "--upgrade"])
    print("done - restart the service (aci stop; then relaunch) for changes to apply.")
    return 0


def _do_onboard(url, key):
    from aci.client import ACIClient
    repo = _repo_root()
    c = ACIClient(url, api_key=key)
    try:
        h = c.health()
    except Exception:
        h = None
    try:
        watched = c.watched()
    except Exception:
        watched = []
    checks = [
        (h is not None, "service running", "start it:  py quickstart.py   (or: aci tray)"),
        (bool(h and h.get("encrypted")), "encryption at rest enabled",
         "enable:  aci set-key --passphrase \"...\""),
        (os.path.exists(_startup_bat()), "starts automatically on login",
         "enable:  aci autostart"),
        (len(watched) > 0, f"auto-watching {len(watched)} folder(s)",
         "add:  aci watch \"C:\\Users\\you\\Documents\""),
        (os.path.exists(os.path.join(repo, ".mcp.json")), "AI bridge (MCP) configured",
         f'register:  claude mcp add aci --env ACI_URL={url} -- py "{os.path.join(repo, "mcp_aci.py")}"'),
        (os.path.isdir(os.path.join(repo, "clients", "browser-extension")), "browser extension available",
         f'load unpacked:  {os.path.join(repo, "clients", "browser-extension")}'),
    ]
    print("\nACI setup readiness\n" + "-" * 40)
    for ok, label, hint in checks:
        print(f"  [{'x' if ok else ' '}] {label}")
        if not ok:
            print(f"        -> {hint}")
    done = sum(1 for ok, _, _ in checks if ok)
    print("-" * 40 + f"\n  {done}/{len(checks)} ready\n")
    return 0


def _do_auto(url, key):
    """One-command autonomy: enable autostart + auto-watch the user's real folders,
    so ACI just runs on its own. No Console operation needed."""
    import subprocess
    import time
    from aci.client import ACIClient

    if os.name == "nt":
        _do_autostart(False)                       # start on every login

    c = ACIClient(url, api_key=key)
    try:
        c.health()
    except Exception:                              # not running -> start it
        subprocess.Popen([sys.executable, "-m", "aci.cli", "serve"], env={**os.environ},
                         creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
        for _ in range(60):
            try:
                c.health()
                break
            except Exception:
                time.sleep(1)

    home = os.path.expanduser("~")
    candidates = [os.path.join(home, d) for d in ("Documents", "Desktop", "Downloads")]
    candidates += [os.path.join(home, "OneDrive", d) for d in ("Documents", "Desktop")]
    watched = []
    for p in candidates:
        if os.path.isdir(p) and p not in watched:
            try:
                c.watch(p, defer=True)             # register; background loop indexes it
                watched.append(p)
            except Exception:
                pass

    print("\nACI is now set up to run on its own:")
    print("  - starts automatically on login (always-on, background)")
    for p in watched:
        print(f"  - auto-watching: {p}")
    print("\nIt will quietly index your documents and keep them searchable - no Console needed.")
    print("Glance at it anytime:   py -m aci.cli tray")
    print("Undo:                   py -m aci.cli autostart --remove")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="aci",
                                description="ACI - Artificial Cognition Infrastructure")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the ACI service")
    s.add_argument("--port", default=None)
    s.add_argument("--db", default=None)
    s.add_argument("--observer", default=None)
    s.add_argument("--api-key", dest="api_key", default=None)

    mo = sub.add_parser("monadise", help="store a monad")
    mo.add_argument("content")
    mo.add_argument("--source", default="DERIVED")
    _client_args(mo)

    rc = sub.add_parser("recall", help="recall by meaning")
    rc.add_argument("query")
    rc.add_argument("--k", type=int, default=5)
    _client_args(rc)

    ph = sub.add_parser("photos", help="semantic image search (needs pillow + CLIP)")
    ph.add_argument("query")
    ph.add_argument("--k", type=int, default=8)
    _client_args(ph)

    va = sub.add_parser("validate", help="validate a statement")
    va.add_argument("statement")
    _client_args(va)

    stt = sub.add_parser("stats", help="health + compression stats")
    _client_args(stt)

    ls = sub.add_parser("monads", help="list stored monads")
    ls.add_argument("--limit", type=int, default=20)
    _client_args(ls)

    fo = sub.add_parser("forget", help="delete a monad")
    fo.add_argument("id")
    _client_args(fo)

    wa = sub.add_parser("watch", help="auto-watch a folder (keeps it synced)")
    wa.add_argument("folder")
    _client_args(wa)

    aus = sub.add_parser("autostart", help="run ACI automatically on login (Windows)")
    aus.add_argument("--remove", action="store_true", help="undo autostart")

    stat = sub.add_parser("status", help="is the ACI service running?")
    _client_args(stat)

    stp = sub.add_parser("stop", help="stop the running ACI service")
    _client_args(stp)

    pz = sub.add_parser("pause", help="pause ALL autonomous capture (privacy)")
    _client_args(pz)
    rz = sub.add_parser("resume", help="resume autonomous capture")
    _client_args(rz)
    cn = sub.add_parser("consent", help="allow/deny a capture source (FILE/WEB/AI/... or a domain/path)")
    cn.add_argument("scope")
    cn.add_argument("state", choices=["on", "off"])
    _client_args(cn)

    dv = sub.add_parser("device", help="device health + optimization recommendations (USP-2)")
    _client_args(dv)
    du = sub.add_parser("dupes", help="scan a folder for duplicate files (smart cleaning)")
    du.add_argument("folder")
    du.add_argument("--min-size", dest="min_size", type=int, default=1 << 20)
    _client_args(du)

    ar = sub.add_parser("archive", help="compress+store files (delete-safe); monadises readable ones")
    ar.add_argument("path")
    _client_args(ar)
    rs = sub.add_parser("restore", help="restore an archived file byte-for-byte")
    rs.add_argument("path")
    rs.add_argument("--dest", default=None)
    _client_args(rs)
    az = sub.add_parser("archive-stats", help="memory-compressor savings + archived files")
    _client_args(az)

    ob = sub.add_parser("observe", help="turn activity observation on/off (Phase D)")
    ob.add_argument("state", choices=["on", "off"])
    _client_args(ob)
    ml = sub.add_parser("mail", help="ingest email over IMAP (Phase D4)")
    ml.add_argument("--host", required=True)
    ml.add_argument("--user", required=True)
    ml.add_argument("--password", required=True)
    ml.add_argument("--folder", default="INBOX")
    ml.add_argument("--limit", type=int, default=50)
    _client_args(ml)

    sk = sub.add_parser("set-key", help="store the encryption passphrase in the OS keystore (DPAPI)")
    sk.add_argument("--passphrase", default=None)

    wp = sub.add_parser("wipe", help="DELETE ALL stored data (right to be forgotten)")
    wp.add_argument("--confirm", action="store_true")
    _client_args(wp)
    bk = sub.add_parser("backup", help="back up the ACI database to a file")
    bk.add_argument("path")
    _client_args(bk)
    cp = sub.add_parser("compact", help="reclaim space (purge superseded/old + VACUUM)")
    cp.add_argument("--purge-superseded", dest="purge", action="store_true")
    cp.add_argument("--older-than-days", dest="older", type=int, default=None)
    _client_args(cp)
    ig = sub.add_parser("integrity", help="run a database integrity check")
    _client_args(ig)

    au = sub.add_parser("auto", help="set ACI up to run on its own (autostart + watch your folders)")
    _client_args(au)
    ca = sub.add_parser("connect-ais", help="auto-register ACI into every MCP-capable AI tool on this machine")
    ca.add_argument("--remove", action="store_true")
    sub.add_parser("tray", help="open the ACI control panel window")
    sub.add_parser("search", help="open the ACI launcher (semantic search bar)")
    sim = sub.add_parser("similar", help="find items similar to a file (used by the right-click menu)")
    sim.add_argument("path")
    shm = sub.add_parser("shellmenu", help="add/remove the Explorer 'ACI: find similar' right-click item")
    shm.add_argument("--remove", action="store_true")
    sub.add_parser("update", help="update ACI (git pull or pip reinstall)")
    on = sub.add_parser("onboard", help="show the setup-readiness checklist")
    _client_args(on)

    a = p.parse_args(argv)

    if a.cmd == "serve":
        from aci.service import main as serve
        return serve(port=a.port, db=a.db, observer=a.observer, api_key=a.api_key)
    if a.cmd == "autostart":
        return _do_autostart(a.remove)
    if a.cmd == "auto":
        return _do_auto(a.url, a.key)
    if a.cmd == "connect-ais":
        from aci import connect_ais
        res = connect_ais.run(remove=a.remove)
        print(json.dumps(res, indent=2))
        return 0
    if a.cmd == "tray":
        from aci.tray import main as tray_main
        return tray_main()
    if a.cmd == "search":
        from aci.launcher import main as launch
        return launch()
    if a.cmd == "similar":
        from aci.documents import load_text, SUPPORTED_EXT
        q = os.path.basename(a.path)
        if os.path.splitext(a.path)[1].lower() in SUPPORTED_EXT:
            t = load_text(a.path)
            if t.strip():
                q = t.strip()[:400]
        from aci.launcher import main as launch
        return launch(q)
    if a.cmd == "shellmenu":
        from aci import shellmenu
        out = shellmenu.remove() if a.remove else shellmenu.install()
        print(json.dumps(out, indent=2))
        return 0
    if a.cmd == "update":
        return _do_update()
    if a.cmd == "onboard":
        return _do_onboard(a.url, a.key)
    if a.cmd == "set-key":
        import os as _os
        from aci.keystore import save_passphrase
        pw = a.passphrase or _os.environ.get("ACI_PASSPHRASE")
        if not pw:
            print("provide --passphrase or set ACI_PASSPHRASE", file=sys.stderr)
            return 1
        try:
            path = save_passphrase(pw)
            print(f"encryption passphrase stored (DPAPI-protected): {path}\n"
                  f"the service will now decrypt automatically - no ACI_PASSPHRASE needed.")
            return 0
        except Exception as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

    from aci.client import ACIClient
    c = ACIClient(a.url, api_key=a.key)
    try:
        if a.cmd == "monadise":
            out = c.monadise(a.content, source_type=a.source)
        elif a.cmd == "recall":
            out = c.recall(a.query, k=a.k)
        elif a.cmd == "photos":
            out = c.recall_images(a.query, k=a.k)
        elif a.cmd == "validate":
            out = c.validate(a.statement)
        elif a.cmd == "stats":
            out = {"health": c.health(), "compress": c.compress()}
        elif a.cmd == "monads":
            out = c.monads(limit=a.limit)
        elif a.cmd == "forget":
            out = c.forget(a.id)
        elif a.cmd == "watch":
            out = c.watch(a.folder)
        elif a.cmd == "status":
            out = {"running": True, **c.health()}
        elif a.cmd == "stop":
            out = c.stop()
        elif a.cmd == "pause":
            out = c.pause(True)
        elif a.cmd == "resume":
            out = c.pause(False)
        elif a.cmd == "consent":
            out = c.consent(a.scope, a.state == "on")
        elif a.cmd == "device":
            out = c.device()
        elif a.cmd == "dupes":
            out = c.scan_dupes(a.folder, a.min_size)
        elif a.cmd == "archive":
            out = c.archive(a.path)
        elif a.cmd == "restore":
            out = c.restore(a.path, a.dest)
        elif a.cmd == "archive-stats":
            out = c.archive_stats()
        elif a.cmd == "observe":
            out = c.observe(a.state == "on")
        elif a.cmd == "mail":
            out = c.ingest_mail(a.host, a.user, a.password, a.folder, a.limit)
        elif a.cmd == "wipe":
            if not a.confirm:
                print("refusing without --confirm (this deletes ALL data)", file=sys.stderr)
                return 1
            out = c.wipe(confirm=True)
        elif a.cmd == "backup":
            out = c.backup(a.path)
        elif a.cmd == "compact":
            out = c.compact(purge_superseded=a.purge, older_than_days=a.older)
        elif a.cmd == "integrity":
            out = c.integrity()
    except Exception as e:
        if a.cmd == "status":
            print(json.dumps({"running": False,
                              "hint": "start with: py quickstart.py  (or: aci serve)"}, indent=2))
            return 0
        if a.cmd == "stop":
            print("service not reachable (already stopped?)")
            return 0
        print(f"error: {e} (is the service running?  aci serve)", file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
