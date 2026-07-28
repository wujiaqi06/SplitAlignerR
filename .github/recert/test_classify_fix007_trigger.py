#!/usr/bin/env python3
"""Unit checks for every authorized Fix007 trigger branch."""

from __future__ import annotations

from classify_fix007_trigger import EXPECTED, classify


def state(default: str = "PASS") -> dict[str, str]:
    return {name: default for name in EXPECTED}


def main() -> None:
    case_a = state()
    case_a["dll_regex_static"] = "TIMEOUT"
    case_a["dll_frozen_numeric"] = "TIMEOUT"
    assert classify(case_a)[0:3:2] == ("A", "TRUE")

    case_a_remediated = state()
    case_a_remediated["dll_regex_automatic"] = "TIMEOUT"
    case_a_remediated["dll_regex_static"] = "TIMEOUT"
    assert classify(case_a_remediated)[0:3:2] == (
        "A_REMEDIATED",
        "FALSE",
    )

    case_b = state()
    case_b["dll_ascii_marker"] = "TIMEOUT"
    assert classify(case_b)[0:3:2] == ("B", "TRUE_MARKER_ONLY")

    case_c = state()
    case_c["package_numeric_validator"] = "TIMEOUT"
    assert classify(case_c)[0:3:2] == ("C", "FALSE")

    assert classify(state())[0:3:2] == (
        "NO_REPRODUCTION_WITHIN_60_SECOND_GATE",
        "FALSE",
    )

    unresolved = state()
    unresolved["dll_frozen_numeric"] = "TIMEOUT"
    assert classify(unresolved)[0:3:2] == ("UNRESOLVED", "FALSE")

    broken = state()
    broken["dll_noop"] = "HARNESS_FAILURE"
    try:
        classify(broken)
    except ValueError:
        pass
    else:
        raise AssertionError("harness failure was classified")
    print(
        "fix007_trigger_rules: PASS "
        "(A,A-remediated,B,C,no-reproduction,unresolved)"
    )


if __name__ == "__main__":
    main()
