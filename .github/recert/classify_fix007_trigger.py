#!/usr/bin/env python3
"""Apply the main-console A/B/C trigger rules to verified hosted evidence."""

from __future__ import annotations

import csv
import pathlib
import sys


EXPECTED = (
    "dll_noop",
    "dll_strtod",
    "dll_ascii_marker",
    "dll_regex_automatic",
    "dll_regex_static",
    "dll_frozen_numeric",
    "package_core_info",
    "package_numeric_validator",
)
SCHEDULE = ("dll_locale",) + EXPECTED


def classify(state: dict[str, str]) -> tuple[str, str, str]:
    """Return trigger, decision, and conditional core authorization."""
    if any(value == "HARNESS_FAILURE" for value in state.values()):
        raise ValueError("harness failure cannot be classified")
    base_fast = all(
        state[name] == "PASS"
        for name in ("dll_noop", "dll_strtod", "dll_ascii_marker")
    )
    regex_timeout = any(
        state[name] == "TIMEOUT"
        for name in ("dll_regex_automatic", "dll_regex_static")
    )
    if base_fast and regex_timeout and state["dll_frozen_numeric"] == "TIMEOUT":
        return (
            "A",
            "ROOT CAUSE CONFIRMED: Windows R-hosted std::regex path",
            "TRUE",
        )
    if (
        base_fast
        and regex_timeout
        and state["dll_frozen_numeric"] == "PASS"
        and state["package_core_info"] == "PASS"
        and state["package_numeric_validator"] == "PASS"
    ):
        return (
            "A_REMEDIATED",
            "FIX007 A REMEDIATION CONFIRMED: frozen and package numeric paths pass",
            "FALSE",
        )
    if (
        state["dll_noop"] == "PASS"
        and state["dll_strtod"] == "PASS"
        and state["dll_ascii_marker"] == "TIMEOUT"
    ):
        return (
            "B",
            "ROOT CAUSE CONFIRMED: Windows R-hosted marker path",
            "TRUE_MARKER_ONLY",
        )
    if all(state[name] == "PASS" for name in EXPECTED[:6]) and (
        state["package_core_info"] == "PASS"
        and state["package_numeric_validator"] == "TIMEOUT"
    ):
        return (
            "C",
            "ROOT CAUSE NOT ISOLATED — PACKAGE DLL/RCPP BOUNDARY",
            "FALSE",
        )
    if all(state[name] == "PASS" for name in EXPECTED):
        return (
            "NO_REPRODUCTION_WITHIN_60_SECOND_GATE",
            "ROOT CAUSE NOT ISOLATED — ALL DECLARED PRIMITIVES PASSED",
            "FALSE",
        )
    return (
        "UNRESOLVED",
        "ROOT CAUSE NOT ISOLATED — LAST COMPLETED STAGES ONLY",
        "FALSE",
    )


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: classify_fix007_trigger.py RESULTS_TSV")
    path = pathlib.Path(sys.argv[1]).resolve()
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if tuple(row.get("case_id", "") for row in rows) != SCHEDULE:
        raise SystemExit("verified Fix007 case schedule is required")
    state = {
        row["case_id"]: row["classification"]
        for row in rows
        if row["case_id"] in EXPECTED
    }
    try:
        trigger, decision, authorized = classify(state)
    except ValueError as error:
        raise SystemExit(str(error)) from error

    print(f"trigger_class: {trigger}")
    print(f"decision: {decision}")
    print(f"core_change_authorized_by_task: {authorized}")
    for case_id in EXPECTED:
        print(f"case_classification: {case_id}|{state[case_id]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
