"""
Windows Explorer right-click integration (#4).

Adds an "ACI: find similar" item to the right-click menu of any file. Clicking it
opens the ACI launcher pre-filled from that file, showing semantically-similar
things ACI knows. Pure stdlib (winreg); per-user (HKCU, no admin needed).

    aci shellmenu            # install
    aci shellmenu --remove   # uninstall
"""
from __future__ import annotations
import os
import sys

_KEY = r"Software\Classes\*\shell\ACIFindSimilar"


def _pythonw() -> str:
    p = sys.executable
    pw = p.replace("python.exe", "pythonw.exe")
    return pw if os.path.exists(pw) else p


def install() -> dict:
    if os.name != "nt":
        raise OSError("Explorer menu is Windows-only")
    import winreg
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pyw = _pythonw()
    code = ("import sys; sys.path.insert(0, r'%s'); from aci.cli import main; "
            "main(['similar', sys.argv[1]])" % repo)
    cmd = '"%s" -c "%s" "%%1"' % (pyw, code)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _KEY) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "ACI: find similar")
        winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, pyw)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _KEY + r"\command") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
    return {"installed": True, "menu": "ACI: find similar", "command": cmd}


def remove() -> dict:
    if os.name != "nt":
        return {"removed": False, "reason": "Windows-only"}
    import winreg
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, _KEY + r"\command")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, _KEY)
        return {"removed": True}
    except FileNotFoundError:
        return {"removed": False, "reason": "not installed"}
