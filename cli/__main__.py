"""
cli/__main__.py — module entry point so ``python -m cli`` works.

Delegates to ``cli.main.main()`` and propagates its integer exit code.
"""

from __future__ import annotations

import sys

from cli.main import main

if __name__ == "__main__":
    sys.exit(main())
