"""Back-compat entry point. The server now lives in the installable package
(`aci.service`). `py server/aci_server.py` still works."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aci.service import main  # noqa: E402

if __name__ == "__main__":
    main()
