#!/usr/bin/env python3
"""Regression checks for the Fix007 normalized parser view."""

from __future__ import annotations

import importlib.util
import pathlib


SCRIPT_DIR = pathlib.Path(__file__).resolve().parent


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    producer = load("cold_producer", "windows_cold_start_probe.py")
    verifier = load(
        "cold_verifier", "verify_windows_cold_start_evidence.py"
    )
    raw = (
        "stage_marker: SCRIPT_STARTED\r\n"
        "stage_marker: NUMERIC_FIRST_CALL_STARTED\r\n"
        "timing_numeric_first_call_wall_seconds: 0.125000000\r\n"
        "case_status: PASS\r\n"
    )
    frozen = raw.encode("utf-8")

    assert producer.normalize_text(raw).count("\r") == 0
    assert producer.last_stage(raw) == "NUMERIC_FIRST_CALL_STARTED"
    assert producer.parse_timings("numeric_validator", raw) == [
        {
            "case_id": "numeric_validator",
            "timing_name": "numeric_first_call",
            "wall_seconds": "0.125000000",
        }
    ]
    assert producer.has_case_completion(raw)
    assert verifier.stage_markers(raw)[-1] == "NUMERIC_FIRST_CALL_STARTED"
    assert verifier.raw_timings("numeric_validator", raw) == [
        {
            "case_id": "numeric_validator",
            "timing_name": "numeric_first_call",
            "wall_seconds": "0.125000000",
        }
    ]
    assert raw.encode("utf-8") == frozen
    print("crlf_normalized_parser_view: PASS")
    print("raw_stream_bytes_unchanged: PASS")


if __name__ == "__main__":
    main()
