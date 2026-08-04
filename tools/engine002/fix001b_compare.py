#!/usr/bin/env python3
"""Compare mandatory FIX001B artifacts without normalizing durable bytes."""

from __future__ import annotations

import argparse
from pathlib import Path


REQUIRED_PLATFORMS = ("linux-release", "macos-release", "windows-release")
HASH_KEYS = (
    "golden_plan_sha256",
    "golden_store_component_sha256",
    "golden_store_manifest_sha256",
    "golden_payload_aggregate_sha256",
    "authority_records_sha256",
    "authority_store_component_sha256",
    "authority_store_manifest_sha256",
    "authority_payload_aggregate_sha256",
    "stress_store_component_sha256",
    "stress_store_manifest_sha256",
    "stress_payload_aggregate_sha256",
)


def parse(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw or raw.startswith("#"):
            continue
        key, separator, value = raw.partition("=")
        if not separator or not key or key in values:
            raise ValueError(f"malformed or duplicate field in {path}: {raw}")
        values[key] = value
    return values


def locate(root: Path, filename: str) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in sorted(root.rglob(filename)):
        values = parse(path)
        platform = values.get("platform_key")
        if platform in REQUIRED_PLATFORMS:
            if platform in found:
                raise ValueError(f"duplicate {filename} for {platform}")
            found[platform] = path
    missing = sorted(set(REQUIRED_PLATFORMS) - set(found))
    if missing:
        raise ValueError(f"missing {filename}: {', '.join(missing)}")
    return found


def write(path: Path, lines: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.artifacts)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    hash_paths = locate(root, "deterministic_hashes.txt")
    result_paths = locate(root, "platform_results.txt")
    hashes = {platform: parse(path) for platform, path in hash_paths.items()}
    results = {platform: parse(path) for platform, path in result_paths.items()}
    for platform in REQUIRED_PLATFORMS:
        if hashes[platform].get("status") != "PASS":
            raise ValueError(f"hash status is not PASS for {platform}")
        if results[platform].get("status") != "PASS":
            raise ValueError(f"platform status is not PASS for {platform}")

    comparisons: dict[str, str] = {}
    for key in HASH_KEYS:
        values = [hashes[platform].get(key) for platform in REQUIRED_PLATFORMS]
        if any(value is None for value in values) or len(set(values)) != 1:
            raise ValueError(f"cross-platform mismatch for {key}: {values}")
        comparisons[key] = values[0]  # type: ignore[assignment]

    write(output / "GOLDEN_BYTE_COMPARISON.txt", [
        "status=PASS",
        "platforms=" + ",".join(REQUIRED_PLATFORMS),
        f"golden_plan_sha256={comparisons['golden_plan_sha256']}",
        f"golden_store_component_sha256={comparisons['golden_store_component_sha256']}",
        f"golden_store_manifest_sha256={comparisons['golden_store_manifest_sha256']}",
        f"golden_payload_aggregate_sha256={comparisons['golden_payload_aggregate_sha256']}",
        "byte_normalization=NONE",
    ])
    write(output / "AUTHORITY_1974_COMPARISON.txt", [
        "status=PASS",
        "platforms=" + ",".join(REQUIRED_PLATFORMS),
        "patterns_per_platform=1974",
        f"authority_records_sha256={comparisons['authority_records_sha256']}",
        f"authority_store_component_sha256={comparisons['authority_store_component_sha256']}",
        f"authority_store_manifest_sha256={comparisons['authority_store_manifest_sha256']}",
        f"authority_payload_aggregate_sha256={comparisons['authority_payload_aggregate_sha256']}",
        f"stress_store_component_sha256={comparisons['stress_store_component_sha256']}",
        f"stress_store_manifest_sha256={comparisons['stress_store_manifest_sha256']}",
        f"stress_payload_aggregate_sha256={comparisons['stress_payload_aggregate_sha256']}",
    ])

    lifecycle_fields = (
        "R_lifecycle_active_pin_busy",
        "R_lifecycle_release_close_double_close",
        "R_lifecycle_read_after_close",
        "R_lifecycle_GC_XPtr",
        "new_R_process_reopen",
        "wrong_authority_rejection",
        "corruption_rejection",
        "missing_or_unvalidated_manifest_rejection",
    )
    for platform in REQUIRED_PLATFORMS:
        for field in lifecycle_fields:
            if results[platform].get(field) != "PASS":
                raise ValueError(f"{platform} lifecycle gate failed: {field}")
    write(output / "R_BOUNDARY_RESULTS.txt", [
        "status=PASS",
        "platforms=" + ",".join(REQUIRED_PLATFORMS),
        *[f"{field}=PASS" for field in lifecycle_fields],
    ])

    windows = results["windows-release"]
    windows_fields = (
        "binary_no_crlf_exact_bytes",
        "atomic_no_replace_preexisting_rejection",
        "atomic_no_replace_original_bytes_preserved",
        "u64_offset_above_4GiB",
        "C_long_truncation_runtime_probe",
    )
    for field in windows_fields:
        if windows.get(field) != "PASS":
            raise ValueError(f"Windows gate failed: {field}")
    if windows.get("windows_physical_store_status") != "PASS":
        raise ValueError("Windows bounded physical store was not executed")
    write(output / "WINDOWS_OFFSET_ATOMICITY_RESULTS.txt", [
        "status=PASS",
        *[f"{field}=PASS" for field in windows_fields],
        f"physical_store_patterns={windows['windows_physical_store_patterns']}",
        f"physical_store_bytes={windows['windows_physical_store_bytes']}",
        f"physical_last_record_lookup={windows['windows_physical_last_record_lookup']}",
        "physical_Windows_store_above_4GiB=NOT_CLAIMED",
        "physical_FIX001_macOS_store_above_4GiB=SEPARATE_ACCEPTED_EVIDENCE",
    ])
    write(output / "CI_JOB_RESULTS.txt", [
        "status=PASS",
        *[f"{platform}=PASS" for platform in REQUIRED_PLATFORMS],
        "comparison=PASS",
    ])
    print("ENGINE002_FIX001B_COMPARISON_PASS")


if __name__ == "__main__":
    main()
