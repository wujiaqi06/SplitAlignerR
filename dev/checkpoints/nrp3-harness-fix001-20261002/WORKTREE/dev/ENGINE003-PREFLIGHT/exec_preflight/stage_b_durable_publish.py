#!/usr/bin/env python3
"""Frozen DurablePublish-v1 subset used by the Stage-B physical prototype.

Publication is a single same-parent exclusive rename.  In particular, this
module never performs an exists check followed by replace.  A losing publisher
receives a typed stop and may clean only its own still-private temporary tree.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, BinaryIO, Callable, Dict


HERE = Path(__file__).resolve().parent
REFERENCE = HERE.parent / "reference"
for value in (HERE, REFERENCE):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from fix001_contract import StopSignal  # noqa: E402
from probe_durability_capabilities import (  # noqa: E402
    rename_exclusive,
    sync_directory,
    sync_file,
)


_VALIDATED_PREFIX = (
    b"SplitAlignerR/ENGINE003StageBBoundedValidated/v2\n"
    b"scope=NON_PRODUCTION_PHYSICAL_PROTOTYPE\n"
    b"manifest_bytes=1024\n"
    b"padding="
)
VALIDATED_BYTES = (
    _VALIDATED_PREFIX
    + b"0" * (1024 - len(_VALIDATED_PREFIX) - 1)
    + b"\n"
)
if len(VALIDATED_BYTES) != 1024:
    raise AssertionError("bounded VALIDATED manifest length")


# P12 freezes the largest read request made by evidence-tree hashing.  The
# digest grammar is unchanged; only the way file payload bytes are supplied to
# hashlib is bounded.
TREE_HASH_CHUNK_BYTES = 1024 * 1024


def _reject_symlink(path: Path) -> None:
    observed = os.lstat(path)
    if stat.S_ISLNK(observed.st_mode):
        raise StopSignal("SB_STOP_PUBLICATION_PATH", f"symlink:{path.name}")


def _sync_regular_file(path: Path) -> str:
    _reject_symlink(path)
    if not path.is_file():
        raise StopSignal("SB_STOP_PUBLICATION_PATH", f"not_regular:{path.name}")
    fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    try:
        status, primitive = sync_file(fd)
    except OSError as error:
        raise StopSignal(
            "SB_STOP_PUBLICATION_DURABILITY",
            f"file_sync:{path.name}:errno={error.errno}",
        ) from error
    finally:
        os.close(fd)
    if status != "PASS":
        raise StopSignal("SB_STOP_PUBLICATION_DURABILITY", f"file_sync:{path.name}")
    return primitive


def _sync_dir(path: Path, stage: str) -> str:
    _reject_symlink(path)
    try:
        status, primitive = sync_directory(path)
    except OSError as error:
        raise StopSignal(
            "SB_STOP_PUBLICATION_DURABILITY",
            f"{stage}:errno={error.errno}",
        ) from error
    if status != "PASS":
        raise StopSignal("SB_STOP_PUBLICATION_DURABILITY", stage)
    return primitive


def _open_binary(path: Path) -> BinaryIO:
    return path.open("rb")


def _stream_file_payload(
        digest: Any, path: Path, expected_size: int,
        open_binary: Callable[[Path], BinaryIO],
        chunk_bytes: int) -> None:
    if type(chunk_bytes) is not int or chunk_bytes < 1:
        raise ValueError("tree hash chunk size must be a positive integer")
    remaining = expected_size
    with open_binary(path) as handle:
        while remaining:
            requested = min(chunk_bytes, remaining)
            raw = handle.read(requested)
            if not raw:
                raise StopSignal(
                    "SB_STOP_EVIDENCE_HASH", f"file_truncated:{path.name}",
                )
            if len(raw) > requested:
                raise StopSignal(
                    "SB_STOP_EVIDENCE_HASH", f"reader_exceeded_request:{path.name}",
                )
            digest.update(raw)
            remaining -= len(raw)
        # A changing evidence tree is not a valid hash input.  This one-byte
        # bounded probe prevents silently hashing only the old prefix if a file
        # grows after its length was encoded.
        if handle.read(1):
            raise StopSignal(
                "SB_STOP_EVIDENCE_HASH", f"file_grew_during_hash:{path.name}",
            )


def tree_sha256(
        root: Path, chunk_bytes: int = TREE_HASH_CHUNK_BYTES,
        open_binary: Callable[[Path], BinaryIO] = _open_binary) -> str:
    """Hash a tree with the frozen grammar and bounded file reads.

    The byte stream remains exactly ``u64le(path length), path, u64le(file
    length), file`` for every regular file in sorted relative-path order.
    """
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        size = path.stat().st_size
        digest.update(len(relative).to_bytes(8, "little"))
        digest.update(relative)
        digest.update(size.to_bytes(8, "little"))
        _stream_file_payload(
            digest, path, size, open_binary, chunk_bytes,
        )
    return digest.hexdigest()


def durable_publish_barriers(
        temp_target: Path, final_target: Path) -> Dict[str, Any]:
    """Run only the frozen DurablePublish-v1 durability barriers.

    Tree hashing is intentionally absent.  This function is the sole operation
    charged to the authoritative ``publication_durability_barriers`` metric.
    """
    if temp_target.parent.resolve() != final_target.parent.resolve():
        raise StopSignal("SB_STOP_PUBLICATION_PATH", "not_same_parent")
    if not temp_target.is_dir():
        raise StopSignal("SB_STOP_PUBLICATION_PATH", "temporary_missing")
    _reject_symlink(temp_target)
    _reject_symlink(temp_target.parent)
    synced = []
    primitives = []
    for path in sorted(temp_target.rglob("*")):
        if path.is_dir():
            _reject_symlink(path)
            continue
        primitives.append(_sync_regular_file(path))
        synced.append(path.relative_to(temp_target).as_posix())
    primitives.append(_sync_dir(temp_target, "temporary_directory_sync"))
    try:
        status, primitive = rename_exclusive(temp_target, final_target)
    except OSError as error:
        if error.errno in (errno.EEXIST, errno.ENOTEMPTY):
            raise StopSignal(
                "SB_STOP_PUBLICATION_DESTINATION_EXISTS",
                "atomic_no_replace_loser",
            ) from error
        raise StopSignal(
            "SB_STOP_PUBLICATION_DURABILITY",
            f"exclusive_rename:errno={error.errno}",
        ) from error
    if status != "PASS":
        raise StopSignal("SB_STOP_PUBLICATION_DURABILITY", "exclusive_rename")
    primitives.append(primitive)
    primitives.append(_sync_dir(final_target.parent, "parent_directory_sync"))

    validated = final_target / "VALIDATED"
    fd = os.open(
        str(validated), os.O_WRONLY | os.O_CREAT | os.O_EXCL |
        getattr(os, "O_CLOEXEC", 0), 0o600,
    )
    try:
        written = 0
        while written < len(VALIDATED_BYTES):
            count = os.write(fd, VALIDATED_BYTES[written:])
            if count <= 0:
                raise OSError(errno.EIO, "short VALIDATED write")
            written += count
        status, manifest_primitive = sync_file(fd)
        if status != "PASS":
            raise OSError(errno.EIO, "manifest sync did not pass")
    except OSError as error:
        raise StopSignal(
            "SB_STOP_PUBLICATION_DURABILITY",
            f"validated_manifest:errno={error.errno}",
        ) from error
    finally:
        os.close(fd)
    primitives.append(manifest_primitive)
    primitives.append(_sync_dir(final_target, "final_directory_sync"))
    return {
        "protocol": "DURABLE_PUBLISH_V1",
        "publication_primitive": primitive,
        "replace_existing_permitted": False,
        "exists_then_replace_emulation": False,
        "same_parent": True,
        "synced_files": synced,
        "barrier_primitives": primitives,
        "validated_manifest_sha256": hashlib.sha256(VALIDATED_BYTES).hexdigest(),
        "authoritative_timing_scope": "DURABLE_PUBLISH_V1_BARRIERS_ONLY",
        "status": "PUBLISHED_VALIDATED_BOUNDED_PROTOTYPE",
    }


def publication_evidence_hashes(
        prepublication_tree_sha256: str, final_target: Path,
        hash_operation=tree_sha256) -> Dict[str, Any]:
    """Produce required integrity hashes outside every decision timer."""
    return {
        "prepublication_tree_sha256": prepublication_tree_sha256,
        "published_tree_sha256_with_validated": hash_operation(final_target),
        "evidence_hash_timing_role": "EVIDENCE_ONLY",
        "evidence_hash_decision_role": "NOT_DECISION_TIMING",
    }


def durable_publish(
        temp_target: Path, final_target: Path,
        hash_operation=tree_sha256) -> Dict[str, Any]:
    """Compatibility wrapper; its total wall time is never decision evidence."""
    before = hash_operation(temp_target)
    result = durable_publish_barriers(temp_target, final_target)
    result.update(publication_evidence_hashes(
        before, final_target, hash_operation,
    ))
    return result


def write_race_result(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
