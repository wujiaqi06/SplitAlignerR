#!/usr/bin/env python3
"""Compatibility entrypoint superseded by the parameterized FIX002 worker.

The reviewed FIX001 bytes remain recoverable from commit f83f26b8.  Active
source must not retain the old hard-coded 129 x 7 x 4 implementation or its
exists-plus-replace publication path, so this filename now delegates to the
exact worker frozen for later Stage-B execution.
"""

from stage_b_worker import main


if __name__ == "__main__":
    main()
