#!/usr/bin/env python3
import argparse
import base64
import csv
import hashlib
import os
from pathlib import Path

EXPECTED_SHA256 = "1927301f1c0cfbcda98714392ac5dfc2f5bf2401ac7031bd8fd5d76ba1734a5e"
EXPECTED_ROWS = 407


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    encoded = os.environ.get("SPLITALIGNERR_RESIDUAL_NA_KEYS_B64", "")
    if not encoded:
        raise SystemExit(
            "SPLITALIGNERR_RESIDUAL_NA_KEYS_B64 is missing; full authority "
            "replay cannot run"
        )
    try:
        payload = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise SystemExit(f"residual authority secret is not valid base64: {exc}")

    digest = hashlib.sha256(payload).hexdigest()
    if digest != EXPECTED_SHA256:
        raise SystemExit(
            f"residual authority digest mismatch: {digest} != {EXPECTED_SHA256}"
        )

    decoded = payload.decode("utf-8")
    rows = list(csv.DictReader(decoded.splitlines(), delimiter="\t"))
    if not rows or list(rows[0]) != ["gene_id", "branch_id"]:
        raise SystemExit("residual authority must contain gene_id and branch_id")
    keys = [(row["gene_id"], row["branch_id"]) for row in rows]
    if len(keys) != EXPECTED_ROWS or len(set(keys)) != EXPECTED_ROWS:
        raise SystemExit("residual authority must contain 407 unique keys")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    output = output_dir / "01_residual_NA_cell_ledger.tsv"
    output.write_bytes(payload)
    Path(args.report).write_text(
        "\n".join(
            [
                "status: PASS",
                f"rows: {len(keys)}",
                f"sha256: {digest}",
                f"output: {output}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
