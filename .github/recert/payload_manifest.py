#!/usr/bin/env python3
import argparse
import gzip
import hashlib
import io
import re
import tarfile
from pathlib import Path

DECLARED_METADATA = {
    "SplitAlignerR/build/vignette.rds",
}

GENERATED_VIGNETTE_TEXT = {
    "SplitAlignerR/inst/doc/quick-start.R",
    "SplitAlignerR/inst/doc/quick-start.html",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_text_line_endings(data: bytes) -> str:
    return data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def normalized(path: str, data: bytes) -> tuple[str, bytes]:
    if path == "SplitAlignerR/DESCRIPTION":
        text = normalize_text_line_endings(data)
        text = re.sub(r"(?m)^Packaged:.*\n?", "", text)
        return "normalized_packaged_field_and_line_endings", text.encode("utf-8")
    if path in GENERATED_VIGNETTE_TEXT:
        text = normalize_text_line_endings(data)
        if path.endswith(".html"):
            text = re.sub(r'(?m)^<html lang="[^"]*">$', '<html lang="">', text)
            classification = "normalized_vignette_locale_and_line_endings"
        else:
            classification = "normalized_vignette_line_endings"
        return classification, text.encode("utf-8")
    if path == "SplitAlignerR/build/partial.rdb":
        return "normalized_gzip_container_metadata", gzip.decompress(data)
    if path in DECLARED_METADATA:
        return "declared_nondeterministic_build_metadata", b""
    return "payload", data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tar", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    rows = []
    aggregate = hashlib.sha256()
    with tarfile.open(args.tar, "r:gz") as archive:
        members = sorted(
            (member for member in archive.getmembers() if member.isfile()),
            key=lambda member: member.name,
        )
        for member in members:
            handle = archive.extractfile(member)
            if handle is None:
                raise SystemExit(f"could not read {member.name}")
            data = handle.read()
            classification, stable = normalized(member.name, data)
            stable_digest = digest(stable) if stable else "EXCLUDED_METADATA"
            if stable:
                aggregate.update(member.name.encode("utf-8") + b"\0")
                aggregate.update(stable_digest.encode("ascii") + b"\n")
            rows.append(
                (
                    member.name,
                    str(len(data)),
                    digest(data),
                    classification,
                    stable_digest,
                )
            )

    output = Path(args.output)
    output.write_text(
        "path\tsize\traw_sha256\tclassification\tnormalized_sha256\n"
        + "".join("\t".join(row) + "\n" for row in rows)
        + f"SEMANTIC_PAYLOAD_AGGREGATE\t\t\t\t{aggregate.hexdigest()}\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
