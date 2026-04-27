"""
Single entry for LeadPilot (MVP / one file to run):
  python leadpilot_single.py --help
Same as:  python -m leadpilot.main
"""

from __future__ import annotations

import sys
from pathlib import Path

_p = Path(__file__).resolve().parent
if str(_p) not in sys.path:
    sys.path.insert(0, str(_p))

from leadpilot.main import main  # noqa: E402

if __name__ == "__main__":
    main()
