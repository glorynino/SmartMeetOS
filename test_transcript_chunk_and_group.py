from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root is on sys.path when run as a script.
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.tools.test_transcript_chunk_and_group import main


if __name__ == "__main__":
    raise SystemExit(main())
