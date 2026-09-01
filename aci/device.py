"""
Device optimization (USP-2, safe tier) - the "ACI makes computing cheaper" face.

This is the SENSE + MODEL + RECOMMEND half of the MACA loop applied to the device:
read-only health metrics + smart-cleaning (duplicate detection) + recommendations.
No risky actuation here (CPU scheduling / power-plan / throttling is the staged,
opt-in tier). The only destructive op, `clean`, deletes ONLY an explicit list of
files the caller chose.

Stdlib-only with graceful degrade: disk via shutil; memory/battery via ctypes on
Windows or /proc on Linux; cpu / battery-health best-effort via PowerShell on
Windows. Any unavailable metric returns None instead of raising.
"""
from __future__ import annotations
import hashlib
import os
import platform
import shutil
import subprocess
import time


def bytes_h(n) -> str:
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"


def _ps(cmd: str, timeout: float = 8.0):
    """Run a PowerShell snippet, return stripped stdout or None (Windows only)."""
    if os.name != "nt":
        return None
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                             capture_output=True, text=True, timeout=timeout,
                             creationflags=subprocess.CREATE_NO_WINDOW)  # no console flash
        v = (out.stdout or "").strip()
        return v or None
    except Exception:
        return None


def disk_report():
    drives = []
    if os.name == "nt":
        import string
        try:
            bitmask = __import__("ctypes").windll.kernel32.GetLogicalDrives()
            mounts = [f"{c}:\\" for i, c in enumerate(string.ascii_uppercase) if bitmask & (1 << i)]
        except Exception:
            mounts = ["C:\\"]
    else:
        mounts = ["/"]
    for d in mounts:
        try:
            u = shutil.disk_usage(d)
            drives.append({"mount": d, "total": u.total, "used": u.used, "free": u.free,
                           "percent_used": round(u.used / u.total * 100, 1) if u.total else 0})
        except Exception:
            pass
    return drives


def memory_report():
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(m)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return {"total": m.ullTotalPhys, "available": m.ullAvailPhys, "percent_used": m.dwMemoryLoad}
        with open("/proc/meminfo") as f:
            info = {}
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    info[parts[0].rstrip(":")] = int(parts[1]) * 1024
        total, avail = info.get("MemTotal", 0), info.get("MemAvailable", 0)
        return {"total": total, "available": avail,
                "percent_used": round((total - avail) / total * 100, 1) if total else 0}
    except Exception:
        return None


def battery_report():
    if os.name != "nt":
        return None
    try:
        import ctypes

        class SPS(ctypes.Structure):
            _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte),
                        ("BatteryLifePercent", ctypes.c_byte), ("SystemStatusFlag", ctypes.c_byte),
                        ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]
        s = SPS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)):
            return None
        pct = s.BatteryLifePercent & 0xFF
        if pct == 255:
            return None                       # no battery (desktop)
        rep = {"percent": pct, "plugged": s.ACLineStatus == 1}
        # best-effort battery HEALTH (full-charge vs design capacity)
        h = _ps("$d=(Get-CimInstance -Namespace root\\WMI -ClassName BatteryStaticData "
                "-ErrorAction Stop).DesignedCapacity; "
                "$f=(Get-CimInstance -Namespace root\\WMI -ClassName BatteryFullChargedCapacity "
                "-ErrorAction Stop).FullChargedCapacity; "
                "if($d -gt 0){[math]::Round(($f/$d)*100,1)}")
        try:
            if h:
                rep["health_percent"] = float(h.split()[0])
        except Exception:
            pass
        return rep
    except Exception:
        return None


def cpu_report():
    try:
        if os.name == "nt":
            v = _ps("(Get-CimInstance Win32_Processor | "
                    "Measure-Object -Property LoadPercentage -Average).Average")
            return {"load_percent": float(v.split()[0])} if v else None
        load = os.getloadavg()[0]
        cores = os.cpu_count() or 1
        return {"load_percent": round(load / cores * 100, 1)}
    except Exception:
        return None


def device_health():
    disks, mem, bat, cpu = disk_report(), memory_report(), battery_report(), cpu_report()
    recs = []
    for d in disks:
        if d["total"] and d["free"] / d["total"] < 0.10:
            recs.append(f"Low disk on {d['mount']}: only {bytes_h(d['free'])} free "
                        f"({100 - d['percent_used']:.0f}%). Run a duplicate scan to reclaim space.")
    if mem and mem.get("percent_used", 0) > 90:
        recs.append(f"High memory pressure ({mem['percent_used']}%). "
                    f"Once observation (Phase D) is on, ACI can prefetch/route to ease this.")
    if bat and bat.get("health_percent") is not None and bat["health_percent"] < 80:
        recs.append(f"Battery health is {bat['health_percent']}% of design capacity - degraded.")
    if cpu and cpu.get("load_percent", 0) > 85:
        recs.append(f"High CPU load ({cpu['load_percent']}%).")
    if not recs:
        recs.append("Device looks healthy.")
    return {"platform": platform.platform(), "disks": disks, "memory": mem,
            "battery": bat, "cpu": cpu, "recommendations": recs}


def _hash_file(fp: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha1()
    with open(fp, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def scan_duplicates(path: str, min_size: int = 1 << 20,
                    time_budget: float = 20.0) -> dict:
    """Find duplicate files (same content) under `path`, >= min_size (default 1 MB).
    Size-groups first, hashes only same-size candidates. Time-boxed so it never hangs."""
    base = os.path.abspath(path)
    by_size = {}
    start = time.time()
    truncated = False
    for root, _, files in os.walk(base):
        for f in files:
            fp = os.path.join(root, f)
            try:
                sz = os.path.getsize(fp)
            except OSError:
                continue
            if sz >= min_size:
                by_size.setdefault(sz, []).append(fp)
        if time.time() - start > time_budget:
            truncated = True
            break
    groups, reclaimable = [], 0
    for sz, paths in by_size.items():
        if len(paths) < 2:
            continue
        by_hash = {}
        for fp in paths:
            try:
                by_hash.setdefault(_hash_file(fp), []).append(fp)
            except OSError:
                continue
        for dups in by_hash.values():
            if len(dups) > 1:
                groups.append({"size": sz, "count": len(dups), "paths": sorted(dups)})
                reclaimable += sz * (len(dups) - 1)
        if time.time() - start > time_budget:
            truncated = True
            break
    groups.sort(key=lambda g: -g["size"] * g["count"])
    return {"scanned_path": base, "duplicate_groups": groups[:100],
            "group_count": len(groups), "reclaimable_bytes": reclaimable,
            "reclaimable_h": bytes_h(reclaimable), "truncated": truncated}


def _user_bases() -> list:
    """Directories a caller is allowed to delete inside — the user's own space only.
    Prevents an over-broad or malicious /clean call from removing system files."""
    bases = [os.path.realpath(os.path.expanduser("~"))]
    for env in ("OneDrive", "OneDriveConsumer"):
        v = os.environ.get(env)
        if v:
            bases.append(os.path.realpath(v))
    for extra in os.environ.get("AIOS_EXTRA_DIRS", "").split(os.pathsep):
        extra = extra.strip().strip('"')
        if extra and os.path.isdir(extra):
            bases.append(os.path.realpath(extra))
    return bases


def _in_user_space(p: str) -> bool:
    rp = os.path.realpath(p)                        # resolves symlinks + ../  (traversal-safe)
    return any(rp == b or rp.startswith(b + os.sep) for b in _user_bases())


def clean(paths) -> dict:
    """Delete an EXPLICIT list of files (never directories), restricted to the user's own
    directories. Paths outside user space (system files, other drives not opted in) are
    REFUSED — a /clean call can never delete files the user didn't put there."""
    freed, deleted, errors = 0, [], []
    for p in paths or []:
        try:
            if not _in_user_space(p):
                errors.append({"path": p, "error": "refused: outside your folders"})
                continue
            if os.path.islink(p):
                errors.append({"path": p, "error": "refused: symlink"})
                continue
            if os.path.isfile(p):
                sz = os.path.getsize(p)
                os.remove(p)
                freed += sz
                deleted.append(p)
            else:
                errors.append({"path": p, "error": "not a file"})
        except OSError as e:
            errors.append({"path": p, "error": str(e)})
    return {"deleted": deleted, "count": len(deleted), "freed_bytes": freed,
            "freed_h": bytes_h(freed), "errors": errors}
