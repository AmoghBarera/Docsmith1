#!/usr/bin/env python3
"""
Entry point: run from the project root so the `docksmith` package resolves.

    python main.py build -t myimage .
    python main.py run myimage
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root (directory containing this file) is on sys.path
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from docksmith.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
