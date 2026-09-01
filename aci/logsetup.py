"""
Structured logging + audit trail (Phase 3 / F3).

Replaces the background loops' silent `except: pass` with logged errors (so failures
are diagnosable, not swallowed) and records sensitive actions (forget/wipe/observe
toggle/capture) to a rotating local audit log next to the DB. Local-only; nothing
is sent anywhere.
"""
from __future__ import annotations
import logging
import os
from logging.handlers import RotatingFileHandler

_configured = False


def setup(db_path: str = None) -> logging.Logger:
    global _configured
    log = logging.getLogger("aci")
    if _configured:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    log.addHandler(sh)
    try:
        logdir = (os.path.dirname(os.path.abspath(db_path))
                  if db_path and db_path != ":memory:" else ".")
        fh = RotatingFileHandler(os.path.join(logdir, "aci.log"),
                                 maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        log.addHandler(fh)
    except Exception:
        pass
    _configured = True
    return log


def audit(event: str) -> None:
    """Record a sensitive action to the audit trail (propagates to aci handlers)."""
    logging.getLogger("aci.audit").info(event)
