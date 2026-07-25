#!/usr/bin/env python3
import argparse
import hashlib
import os
import stat
import zipfile
from pathlib import Path

FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-zip", required=True)
    args = parser.parse_args()

    source = Path(args.input_dir).resolve()
    output = Path(args.output_zip).resolve()
    if output.is_relative_to(source):
        raise SystemExit("output ZIP must be outside the evidence directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise SystemExit(f"refusing to overwrite {output}")

    files = sorted(path for path in source.rglob("*") if path.is_file())
    with zipfile.ZipFile(
        output, mode="x", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in files:
            relative = path.relative_to(source).as_posix()
            info = zipfile.ZipInfo(relative, date_time=FIXED_TIME)
            mode = stat.S_IMODE(path.stat().st_mode)
            info.external_attr = (mode & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes(), compresslevel=9)

    digest = sha256(output)
    output.with_suffix(output.suffix + ".sha256").write_bytes(
        f"{digest}  {output.name}\n".encode("utf-8")
    )


if __name__ == "__main__":
    main()
