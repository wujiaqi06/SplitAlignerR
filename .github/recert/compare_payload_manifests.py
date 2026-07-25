#!/usr/bin/env python3
import argparse
import csv
from pathlib import Path


def read_manifest(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows or set(rows[0]) != {
        "path",
        "size",
        "raw_sha256",
        "classification",
        "normalized_sha256",
    }:
        raise SystemExit(f"invalid payload manifest: {path}")
    indexed = {row["path"]: row for row in rows}
    if len(indexed) != len(rows):
        raise SystemExit(f"duplicate paths in payload manifest: {path}")
    return indexed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first", required=True)
    parser.add_argument("--second", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    first = read_manifest(Path(args.first))
    second = read_manifest(Path(args.second))
    first_paths = set(first)
    second_paths = set(second)
    path_set_equal = first_paths == second_paths
    common = sorted(first_paths & second_paths)

    normalized_mismatches = []
    undeclared_raw_mismatches = []
    declared_raw_mismatches = []
    for path in common:
        left = first[path]
        right = second[path]
        normalized_equal = (
            left["classification"] == right["classification"]
            and left["normalized_sha256"] == right["normalized_sha256"]
        )
        if not normalized_equal:
            normalized_mismatches.append(path)
        if left["raw_sha256"] != right["raw_sha256"]:
            if left["classification"] == right["classification"] == "payload":
                undeclared_raw_mismatches.append(path)
            else:
                declared_raw_mismatches.append(path)

    passed = (
        path_set_equal
        and not normalized_mismatches
        and not undeclared_raw_mismatches
    )
    report = [
        f"path_set_equal: {path_set_equal}",
        f"first_file_count: {len(first)}",
        f"second_file_count: {len(second)}",
        f"normalized_mismatch_count: {len(normalized_mismatches)}",
        f"undeclared_raw_mismatch_count: {len(undeclared_raw_mismatches)}",
        f"declared_raw_mismatch_count: {len(declared_raw_mismatches)}",
    ]
    report.extend(
        f"normalized_mismatch: {path}" for path in normalized_mismatches
    )
    report.extend(
        f"undeclared_raw_mismatch: {path}"
        for path in undeclared_raw_mismatches
    )
    report.extend(
        f"declared_raw_mismatch: {path}" for path in declared_raw_mismatches
    )
    report.append(f"overall_status: {'PASS' if passed else 'FAIL'}")
    Path(args.report).write_text("\n".join(report) + "\n", encoding="utf-8")
    if not passed:
        raise SystemExit("repeat-build semantic payload comparison failed")


if __name__ == "__main__":
    main()
