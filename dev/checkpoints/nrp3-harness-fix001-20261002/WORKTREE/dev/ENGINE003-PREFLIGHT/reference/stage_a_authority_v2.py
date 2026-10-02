#!/usr/bin/env python3
"""Deterministic Stage-A authority descriptors for ENGINE003 preflight.

This review-only generator emits identity metadata; it performs no timing and
is not a production authority or matrix writer.
``species_authority_template_descriptor_sha256`` is the SHA-256 of the exact
bytes produced by
``json.dumps(descriptor, indent=2, ensure_ascii=True) + "\\n"`` encoded as
UTF-8.  That explicit encoding contract makes the identity independently
reproducible and does not claim that arbitrary JSON serializations are equal.
Every template has ``gene_ids=[]`` and ``bstar_members=[]``: it freezes only
the taxon/primitive authority payload and must not be represented as the SHA
of a future complete Stage-A case external descriptor.  Each future run must
record that complete external descriptor SHA separately.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from encode_tiny_fixture import DESCRIPTOR_SCHEMA, species_authority_digest


COMB_CONSTRUCTION = "ENGINE003_STAGE_A_COMB_AUTHORITY_V1"
STORAGE_CONSTRUCTION = "ENGINE003_STAGE_A_STORAGE_ONLY_AUTHORITY_V1"
TINY_CONSTRUCTION = "ENGINE003_TINY_REGENERATED_AUTHORITY_V1"
FORMULA_ID = "ENGINE003_STAGE_A_AUTHORITY_AWARE_BITS_V2"

EXPECTED_IDENTITIES = {
    "tiny_correctness": (
        "4a3a1bcc8c28154b14e58877ad562e1e514aca00c0ee12d4572d8a1f9ff52953",
        "6b6340b283230cab60230ab79e466e1da06dd0b75df462af6b88bbee245fd25d",
    ),
    "catnip10_like": (
        "27e7f8bf332120c1ae0e3be8e7bf4b1c6db2e90d0ca99cf4e8815432d6d4ecc9",
        "0e046382095d07a7c3e9c0d5e1614f738bd7d42905b9c835fe7b729138c78dd4",
    ),
    "authority_shape": (
        "7641cf8a1efae8cccc3605113284d113ad9f45b143776d0f14b78133a4776942",
        "74d42d998f60afb50dd2d089f86d5211a4aef5cecf82de5cd3417b6a71aa3160",
    ),
    "moderate_churn": (
        "686942e422cde83aaf91c115e0e324a28c9560e3a9a589cfc201a9fecd822654",
        "c18dd6981570b20b89418a415b79411e2510361ccbc8fe183fd81c9c33737751",
    ),
    "large_projected": (
        "42499ecabf6916e7edf5bb7fc9a17f7a181922ccc19b867b391dea2d452fa2b1",
        "cafbfbf6261d206d88018ba03d4b47e358de773a3143f819ee3267890fb67334",
    ),
}


def canonical_descriptor_bytes(descriptor: dict) -> bytes:
    return (json.dumps(descriptor, indent=2, ensure_ascii=True) + "\n").encode(
        "utf-8"
    )


def canonical_split(taxon_count: int, selected: int) -> bytes:
    width = (taxon_count + 7) // 8
    all_mask = (1 << taxon_count) - 1
    complement = all_mask ^ selected
    selected_bytes = selected.to_bytes(width, "little")
    complement_bytes = complement.to_bytes(width, "little")
    # Python 3.9 portability: int.bit_count() is not available on every
    # supported runner, while this reference-only path needs no fast popcount.
    selected_count = bin(selected).count("1")
    complement_count = bin(complement).count("1")
    if selected_count > complement_count:
        return complement_bytes
    if selected_count == complement_count and selected_bytes > complement_bytes:
        return complement_bytes
    return selected_bytes


def descriptor_from_primitives(taxon_count: int, primitives: list[dict]) -> dict:
    return {
        "descriptor_schema": DESCRIPTOR_SCHEMA,
        "taxon_label_bytes_hex": [
            (f"stagea_taxon_{taxon_id:08d}").encode("ascii").hex()
            for taxon_id in range(taxon_count)
        ],
        "primitive_entries": primitives,
        "gene_ids": [],
        "bstar_members": [],
    }


def terminal_primitives(taxon_count: int) -> list[dict]:
    width = (taxon_count + 7) // 8
    return [
        {
            "terminal": True,
            "terminal_taxon_id": taxon_id,
            "authority_edge_split_hex": (1 << taxon_id).to_bytes(
                width, "little"
            ).hex(),
        }
        for taxon_id in range(taxon_count)
    ]


def comb_descriptor(branch_count: int) -> dict:
    if branch_count not in (17, 601, 1997):
        raise ValueError("comb branch count must be 17, 601 or 1997")
    taxon_count = (branch_count + 3) // 2
    primitives = terminal_primitives(taxon_count)
    for k in range(2, taxon_count - 1):
        primitives.append({
            "terminal": False,
            "terminal_taxon_id": 0xFFFFFFFF,
            "authority_edge_split_hex": canonical_split(
                taxon_count, (1 << k) - 1
            ).hex(),
        })
    if len(primitives) != branch_count:
        raise AssertionError("comb primitive count mismatch")
    return descriptor_from_primitives(taxon_count, primitives)


def storage_only_descriptor() -> dict:
    taxon_count = 999
    primitives = terminal_primitives(taxon_count)
    primitives.append({
        "terminal": False,
        "terminal_taxon_id": 0xFFFFFFFF,
        "authority_edge_split_hex": canonical_split(taxon_count, 0b11).hex(),
    })
    if len(primitives) != 1000:
        raise AssertionError("storage-only primitive count mismatch")
    return descriptor_from_primitives(taxon_count, primitives)


def tiny_descriptor() -> dict:
    return {
        "descriptor_schema": DESCRIPTOR_SCHEMA,
        "taxon_label_bytes_hex": ["41", "42", "43", "44"],
        "primitive_entries": [
            {"terminal": True, "terminal_taxon_id": 0,
             "authority_edge_split_hex": "01"},
            {"terminal": True, "terminal_taxon_id": 1,
             "authority_edge_split_hex": "02"},
            {"terminal": True, "terminal_taxon_id": 2,
             "authority_edge_split_hex": "04"},
            {"terminal": True, "terminal_taxon_id": 3,
             "authority_edge_split_hex": "08"},
            {"terminal": False, "terminal_taxon_id": 0xFFFFFFFF,
             "authority_edge_split_hex": "03"},
        ],
        "gene_ids": [],
        "bstar_members": [],
    }


def identity_record(
    case_id: str, construction: str, descriptor: dict, axis_scope: str,
) -> dict:
    raw = canonical_descriptor_bytes(descriptor)
    primitives = descriptor["primitive_entries"]
    terminal_count = sum(bool(item["terminal"]) for item in primitives)
    return {
        "case_id": case_id,
        "formula_id": FORMULA_ID,
        "construction": construction,
        "axis_scope": axis_scope,
        "taxon_count": len(descriptor["taxon_label_bytes_hex"]),
        "primitive_count": len(primitives),
        "terminal_count": terminal_count,
        "internal_count": len(primitives) - terminal_count,
        "descriptor_bytes": len(raw),
        "species_authority_template_descriptor_sha256": (
            hashlib.sha256(raw).hexdigest()
        ),
        "species_authority_v1_sha256": species_authority_digest(descriptor).hex(),
    }


def records() -> list[dict]:
    output = [identity_record(
        "tiny_correctness", TINY_CONSTRUCTION, tiny_descriptor(),
        "SYNTHETIC_TREE_COMPLETE_PRIMITIVE_AXIS",
    )]
    for case_id, branch_count in (
        ("catnip10_like", 17),
        ("authority_shape", 601),
    ):
        output.append(identity_record(
            case_id, COMB_CONSTRUCTION, comb_descriptor(branch_count),
            "BINARY_COMB_TREE_COMPLETE_PRIMITIVE_AXIS",
        ))
    output.append(identity_record(
        "moderate_churn", STORAGE_CONSTRUCTION, storage_only_descriptor(),
        "STORAGE_ONLY_NON_TREE_COMPLETE_PRIMITIVE_AXIS",
    ))
    output.append(identity_record(
        "large_projected", COMB_CONSTRUCTION, comb_descriptor(1997),
        "BINARY_COMB_TREE_COMPLETE_PRIMITIVE_AXIS",
    ))
    return output


def render_tsv(values: list[dict]) -> str:
    keys = (
        "case_id", "formula_id", "construction", "axis_scope", "taxon_count",
        "primitive_count", "terminal_count", "internal_count", "descriptor_bytes",
        "species_authority_template_descriptor_sha256",
        "species_authority_v1_sha256",
    )
    rows = ["\t".join(keys)]
    rows.extend("\t".join(str(value[key]) for key in keys) for value in values)
    return "\n".join(rows) + "\n"


def assert_frozen_identities(values: list[dict]) -> None:
    if {value["case_id"] for value in values} != set(EXPECTED_IDENTITIES):
        raise AssertionError("Stage-A identity case set mismatch")
    for value in values:
        expected_template, expected_species = EXPECTED_IDENTITIES[value["case_id"]]
        if value["formula_id"] != FORMULA_ID:
            raise AssertionError(f"formula identifier mismatch: {value['case_id']}")
        if value["species_authority_template_descriptor_sha256"] != expected_template:
            raise AssertionError(f"template identity mismatch: {value['case_id']}")
        if value["species_authority_v1_sha256"] != expected_species:
            raise AssertionError(f"SpeciesAuthority identity mismatch: {value['case_id']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--format", choices=("tsv", "json"), default="tsv")
    parser.add_argument(
        "--output", type=Path,
        help="optional output path; its parent must already exist",
    )
    args = parser.parse_args()
    values = records()
    assert_frozen_identities(values)
    if args.format == "json":
        rendered = json.dumps(values, indent=2, sort_keys=True) + "\n"
    else:
        rendered = render_tsv(values)
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_bytes(rendered.encode("utf-8"))
        print(
            f"STAGE_A_AUTHORITY_IDENTITIES_PASS {len(values)}/{len(values)} "
            f"format={args.format} output={args.output}"
        )


if __name__ == "__main__":
    main()
