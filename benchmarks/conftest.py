"""Shared fixtures for the CodSpeed benchmark suite.

The project ships flat top-level modules rather than a package, so the
repository root is put on ``sys.path`` to make them importable regardless of
where ``pytest`` is invoked from.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
