"""Back-compat shim: the canonical client now lives in the installable package
(`aci.client`). Existing imports `from clients.connector import ACIClient` keep working."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aci.client import ACIClient  # noqa: F401,E402

__all__ = ["ACIClient"]
