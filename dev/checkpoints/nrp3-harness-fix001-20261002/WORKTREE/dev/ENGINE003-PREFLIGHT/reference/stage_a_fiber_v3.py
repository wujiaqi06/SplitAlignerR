#!/usr/bin/env python3
"""Review-only executable oracle for Stage-A fiber-consistent payloads.

No timing is performed.  The program freezes complete external descriptors,
evaluates every generated row, enforces CompositeRowConsistency-v1, and emits
semantic witness counts plus byte-stream hashes.  It is not a matrix writer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from itertools import combinations
from pathlib import Path

from encode_tiny_fixture import (
    STATE_MAPPED,
    STATE_NA_FUSE,
    STATE_NA_STRUCT,
    STATE_NA_TOPO,
    bstar_registry_digest,
    canonical_bstar_members,
    gene_registry_digest,
    numeric_registry_digest,
    species_authority_digest,
    validate_composite_row_consistency_v1,
    validate_primitive_row_consistency_v1,
)
from stage_a_authority_v2 import (
    COMB_CONSTRUCTION,
    STORAGE_CONSTRUCTION,
    TINY_CONSTRUCTION,
    canonical_descriptor_bytes,
    comb_descriptor,
    storage_only_descriptor,
    tiny_descriptor,
)


FORMULA_ID = "ENGINE003_STAGE_A_FIBER_CONSISTENT_BITS_V3"
EXPECTED_IDENTITIES: dict[str, tuple[str, str, str, str, str]] = {
    "tiny_correctness": (
        "43c59eb1beb797483235a52cc43422a372fff78378ab1b7347f9fc4e222ad3c5",
        "6b6340b283230cab60230ab79e466e1da06dd0b75df462af6b88bbee245fd25d",
        "36f4fa3bca88a6490bfc67d936f9b0167b6f90e0ba711fd7b942a21a4281997c",
        "b5a92c2c982330a69a27539432de46865c0b40ccf71fdea646667f5cc6142a03",
        "29ccc16616d83cf19761d3131e62a768dc5169668d6c952890609893db859d8e",
    ),
    "catnip10_like": (
        "53649108faec60caf33eae69e5a5b22147abcf93130af22e25cc9cdc98aeff99",
        "0e046382095d07a7c3e9c0d5e1614f738bd7d42905b9c835fe7b729138c78dd4",
        "227bece88355fddb428924d6e76ad0b45b3051c140e97cab7b71f0886d10886c",
        "9bd2644882e40b6916e67c81a45d018be396c480e81383a07bb95139ab8d6ccd",
        "195f1af662bf558f104b9836985852b3030e3034098d7f5096a18c0a89f0e266",
    ),
    "authority_shape": (
        "3d2b5b5ff45e053d463978684df16633ad540ee225edc47ab0fbd7510a188fed",
        "74d42d998f60afb50dd2d089f86d5211a4aef5cecf82de5cd3417b6a71aa3160",
        "377bc100ced2ee5ccd8eb696fcf8d8bd763d922cfc4f1102f7972ad86fd57d8f",
        "15fd51b4aaff77332db93158aea8f5393d42b5bab3ceb3866af449097f9d4f33",
        "1cb0e650a5b9641c7e0f1402313e9033021b7a34da234c5215d62b33a322ce18",
    ),
    "moderate_churn": (
        "79785f8c0d9dc2f1d1834809ecdf362d050764af7cb7ebc17928a76b5921ec4f",
        "c18dd6981570b20b89418a415b79411e2510361ccbc8fe183fd81c9c33737751",
        "296b1075fb0defaeee656e4f6e0e3a2787dc3fe3893f7618bc49539ea6583eec",
        "9aec24333a1726558c951303f121b4bf967454036810c45a1a264b1f12ad4291",
        "7978f97d93ad3d8c4cedc5336df342c8fc06a9d45e68e418fa11288763a2b20b",
    ),
}
WITNESS_KEYS = (
    "mapped_valid", "mapped_unavailable", "na_struct", "na_fuse",
    "na_topo_internal", "composite_valid", "composite_invalid",
    "composite_candidate_overlap_rejected",
    "rows_with_two_or_more_valid_composites",
)
EXPECTED_WITNESS_COUNTS = {
    "tiny_correctness": (2, 2, 5, 5, 1, 1, 5, 0, 0),
    "catnip10_like": (42, 9, 50, 51, 18, 13, 67, 7, 3),
    "authority_shape": (
        341819, 57254, 399072, 399073, 170057, 92441, 1010934, 89408, 2275,
    ),
    "moderate_churn": (
        2499999, 832501, 3332500, 3332500, 2500, 1348335, 8651665,
        1316333, 10000,
    ),
}


class ContinuousBitHasher:
    def __init__(self) -> None:
        self.digest = hashlib.sha256()
        self.current = 0
        self.used = 0
        self.byte_count = 0

    def add(self, value: bool) -> None:
        if value:
            self.current |= 1 << self.used
        self.used += 1
        if self.used == 8:
            self.digest.update(bytes([self.current]))
            self.byte_count += 1
            self.current = 0
            self.used = 0

    def finish(self) -> tuple[str, int]:
        if self.used:
            self.digest.update(bytes([self.current]))
            self.byte_count += 1
            self.current = 0
            self.used = 0
        return self.digest.hexdigest(), self.byte_count


def canonical_pairs(primitive_count: int, count: int) -> list[list[int]]:
    # Pairs three positions apart make equal terminal-state phases common while
    # leaving multiple disjoint fibers available in the same row.  The final
    # three wrap probes fill K=B shapes without changing the canonical sort.
    raw_pairs = [[left, left + 3] for left in range(max(0, primitive_count - 3))]
    for left in range(min(3, primitive_count)):
        if left + 6 < primitive_count:
            raw_pairs.append([left, left + 6])
    observed = {tuple(value) for value in raw_pairs}
    if len(raw_pairs) < count:
        for left, right in combinations(range(primitive_count), 2):
            if (left, right) not in observed:
                raw_pairs.append([left, right])
                observed.add((left, right))
            if len(raw_pairs) >= count:
                break
    if len(raw_pairs) < count:
        raise ValueError("insufficient distinct B* pairs for Stage-A case")
    candidates = [
        (struct.pack("<II", left, right), [left, right])
        for left, right in raw_pairs[:count]
    ]
    candidates.sort(key=lambda item: item[0])
    return [members for _encoded, members in candidates]


def complete_descriptor(case_id: str, rows: int, primitive_count: int,
                        bstar_count: int) -> tuple[dict, str, str]:
    if case_id == "tiny_correctness":
        descriptor = tiny_descriptor()
        descriptor["gene_ids"] = ["g0", "g1", "g2"]
        descriptor["bstar_members"] = [[0, 3], [1, 4]]
        construction = TINY_CONSTRUCTION
        axis_scope = "SYNTHETIC_TREE_COMPLETE_PRIMITIVE_AXIS"
    elif case_id in ("catnip10_like", "authority_shape"):
        descriptor = comb_descriptor(primitive_count)
        descriptor["gene_ids"] = [
            f"stagea_gene_{row:08d}" for row in range(rows)
        ]
        descriptor["bstar_members"] = canonical_pairs(
            primitive_count, bstar_count
        )
        construction = COMB_CONSTRUCTION
        axis_scope = "BINARY_COMB_TREE_COMPLETE_PRIMITIVE_AXIS"
    elif case_id == "moderate_churn":
        descriptor = storage_only_descriptor()
        descriptor["gene_ids"] = [
            f"stagea_gene_{row:08d}" for row in range(rows)
        ]
        descriptor["bstar_members"] = canonical_pairs(
            primitive_count, bstar_count
        )
        construction = STORAGE_CONSTRUCTION
        axis_scope = "STORAGE_ONLY_NON_TREE_COMPLETE_PRIMITIVE_AXIS"
    else:
        raise ValueError(f"unknown executed Stage-A case: {case_id}")
    return descriptor, construction, axis_scope


def primitive_state(terminal: bool, row: int, primitive: int) -> int:
    return ((row + 2 * primitive) % 3 if terminal
            else (row + 3 * primitive + 1) % 4)


def evaluate(case_id: str, rows: int, primitive_count: int,
             bstar_count: int) -> tuple[dict, bytes]:
    descriptor, construction, axis_scope = complete_descriptor(
        case_id, rows, primitive_count, bstar_count
    )
    raw = canonical_descriptor_bytes(descriptor)
    if len(descriptor["primitive_entries"]) != primitive_count:
        raise AssertionError("primitive construction shape mismatch")
    if len(descriptor["gene_ids"]) != rows:
        raise AssertionError("gene construction shape mismatch")
    encoded = canonical_bstar_members(
        descriptor["bstar_members"], primitive_count
    )
    species = species_authority_digest(descriptor)
    genes = gene_registry_digest(descriptor["gene_ids"])
    bstar = bstar_registry_digest(species, encoded)
    numeric_registry = numeric_registry_digest(
        species, primitive_count, bstar, encoded
    )
    terminal_flags = [entry["terminal"] for entry in descriptor["primitive_entries"]]
    coordinate_count = primitive_count + bstar_count
    state_hash = hashlib.sha256()
    numeric_hash = hashlib.sha256()
    validity_hash = ContinuousBitHasher()
    counts = {
        "mapped_valid": 0,
        "mapped_unavailable": 0,
        "na_struct": 0,
        "na_fuse": 0,
        "na_topo_internal": 0,
        "composite_valid": 0,
        "composite_invalid": 0,
        "composite_candidate_overlap_rejected": 0,
        "rows_with_two_or_more_valid_composites": 0,
    }
    for row in range(rows):
        states = [
            primitive_state(terminal_flags[primitive], row, primitive)
            for primitive in range(primitive_count)
        ]
        primitive_valid = [
            state == STATE_MAPPED and ((row + 5 * primitive) % 4 != 0)
            for primitive, state in enumerate(states)
        ]
        occupied: set[int] = set()
        composite_valid = []
        for bstar_id, members in enumerate(descriptor["bstar_members"]):
            candidate = (
                ((row + 7 * bstar_id + 1) % 5 != 0)
                and all(states[member] == STATE_NA_FUSE for member in members)
            )
            valid = candidate and not occupied.intersection(members)
            if candidate and not valid:
                counts["composite_candidate_overlap_rejected"] += 1
            if valid:
                occupied.update(members)
            composite_valid.append(valid)
        validity = primitive_valid + composite_valid
        validate_primitive_row_consistency_v1(
            descriptor, states, validity, f"{case_id} row {row}"
        )
        validate_composite_row_consistency_v1(
            descriptor, states, validity, f"{case_id} row {row}"
        )
        if sum(composite_valid) >= 2:
            counts["rows_with_two_or_more_valid_composites"] += 1
        state_hash.update(bytes(states))
        numeric_row = bytearray(coordinate_count * 8)
        for primitive, state in enumerate(states):
            if state == STATE_MAPPED:
                key = "mapped_valid" if primitive_valid[primitive] else "mapped_unavailable"
            elif state == STATE_NA_STRUCT:
                key = "na_struct"
            elif state == STATE_NA_FUSE:
                key = "na_fuse"
            elif terminal_flags[primitive]:
                raise AssertionError("terminal primitive received NA_topo")
            else:
                key = "na_topo_internal"
            counts[key] += 1
        counts["composite_valid"] += sum(composite_valid)
        counts["composite_invalid"] += bstar_count - sum(composite_valid)
        for coordinate, valid in enumerate(validity):
            validity_hash.add(valid)
            if valid:
                linear = row * coordinate_count + coordinate
                bits = 0x3FF0000000000000 | (linear & 0x000FFFFFFFFFFFFF)
                struct.pack_into("<Q", numeric_row, coordinate * 8, bits)
        numeric_hash.update(numeric_row)
    validity_sha, validity_bytes = validity_hash.finish()
    terminal_count = sum(terminal_flags)
    record = {
        "case_id": case_id,
        "execution_status": "SEMANTIC_ORACLE_EXECUTED_NO_TIMING",
        "formula_id": FORMULA_ID,
        "construction": construction,
        "axis_scope": axis_scope,
        "row_count": rows,
        "primitive_count": primitive_count,
        "bstar_count": bstar_count,
        "numeric_coordinate_count": coordinate_count,
        "terminal_count": terminal_count,
        "internal_count": primitive_count - terminal_count,
        "complete_descriptor_bytes": len(raw),
        "complete_descriptor_sha256": hashlib.sha256(raw).hexdigest(),
        "species_authority_sha256": species.hex(),
        "gene_registry_sha256": genes.hex(),
        "bstar_registry_sha256": bstar.hex(),
        "numeric_coordinate_registry_sha256": numeric_registry.hex(),
        "state_stream_sha256": state_hash.hexdigest(),
        "numeric_stream_sha256": numeric_hash.hexdigest(),
        "validity_stream_sha256": validity_sha,
        "validity_stream_bytes": validity_bytes,
        **counts,
    }
    if not counts["mapped_unavailable"]:
        raise AssertionError(f"{case_id}: mapped-but-unavailable witness absent")
    if not counts["na_topo_internal"]:
        raise AssertionError(f"{case_id}: internal NA_topo witness absent")
    if bstar_count and (
        not counts["composite_valid"] or not counts["composite_invalid"]
    ):
        raise AssertionError(f"{case_id}: both composite validity states required")
    return record, raw


def cases() -> list[tuple[str, int, int, int]]:
    return [
        ("tiny_correctness", 3, 5, 2),
        ("catnip10_like", 10, 17, 8),
        ("authority_shape", 2275, 601, 485),
        ("moderate_churn", 10000, 1000, 1000),
    ]


def render_tsv(records: list[dict]) -> str:
    keys = list(records[0])
    rows = ["\t".join(keys)]
    rows.extend("\t".join(str(record[key]) for key in keys) for record in records)
    return "\n".join(rows) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--descriptor-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--write-missing", action="store_true",
        help="write absent descriptor files; existing bytes are never overwritten",
    )
    parser.add_argument(
        "--allow-unfrozen-bootstrap", action="store_true",
        help="permit empty EXPECTED_IDENTITIES only during initial FIX004 freeze",
    )
    args = parser.parse_args()
    records = []
    payloads = {}
    for case in cases():
        record, raw = evaluate(*case)
        records.append(record)
        payloads[record["case_id"]] = raw
    if EXPECTED_IDENTITIES:
        for record in records:
            expected = EXPECTED_IDENTITIES.get(record["case_id"])
            observed = (
                record["complete_descriptor_sha256"],
                record["species_authority_sha256"],
                record["state_stream_sha256"],
                record["numeric_stream_sha256"],
                record["validity_stream_sha256"],
            )
            if expected != observed:
                raise SystemExit(f"frozen Stage-A V3 identity mismatch: {record['case_id']}")
            observed_counts = tuple(record[key] for key in WITNESS_KEYS)
            if EXPECTED_WITNESS_COUNTS.get(record["case_id"]) != observed_counts:
                raise SystemExit(
                    f"frozen Stage-A V3 witness-count mismatch: {record['case_id']}"
                )
    elif not args.allow_unfrozen_bootstrap:
        raise SystemExit("Stage-A V3 identities have not yet been frozen")
    args.descriptor_dir.mkdir(parents=True, exist_ok=True)
    for case_id, raw in payloads.items():
        path = args.descriptor_dir / f"{case_id}.json"
        if path.exists():
            if path.read_bytes() != raw:
                raise SystemExit(f"committed descriptor mismatch: {path}")
        elif args.write_missing:
            path.write_bytes(raw)
        else:
            raise SystemExit(f"missing committed descriptor: {path}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_tsv(records), encoding="utf-8")
    print(f"STAGE_A_V3_SEMANTIC_ORACLE_PASS {len(records)}/{len(records)} NO_TIMING")


if __name__ == "__main__":
    main()
