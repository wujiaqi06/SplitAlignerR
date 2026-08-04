#!/usr/bin/env python3
"""Write deterministic SHA-256 sidecars without platform shell dependencies."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    output = Path(args.output).resolve()
    files = sorted(
        (path for path in root.rglob("*") if path.is_file() and path != output),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    lines = [f"{digest(path)}  {path.relative_to(root).as_posix()}" for path in files]
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
