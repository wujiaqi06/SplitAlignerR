#!/usr/bin/env python3
"""Compatibility entrypoint superseded by the FIX002 controller.

Use ``run_fix002_preflight.py`` in new automation.  The prior implementation
is immutable at commit f83f26b8; active source delegates so it cannot silently
exercise a fixture-specific worker after FIX002.
"""

from run_fix002_preflight import main


if __name__ == "__main__":
    main()
