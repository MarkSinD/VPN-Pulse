"""`python -m vpnpulse.cli` — the same entry point as the `vpn-pulse` console script."""
from __future__ import annotations

import sys

from vpnpulse.cli import main

if __name__ == "__main__":
    sys.exit(main())
