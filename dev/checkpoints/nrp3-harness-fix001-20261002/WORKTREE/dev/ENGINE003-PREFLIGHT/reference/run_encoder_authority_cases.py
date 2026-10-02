#!/usr/bin/env python3
"""Reference-encoder SpeciesAuthority-v1 rejection corpus."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from encode_tiny_fixture import DESCRIPTOR_SCHEMA, species_authority_digest


BASE = {
    "descriptor_schema": DESCRIPTOR_SCHEMA,
    "taxon_label_bytes_hex": ["41", "42", "43", "44"],
    "primitive_entries": [
        {"terminal": True, "terminal_taxon_id": 0, "authority_edge_split_hex": "01"},
        {"terminal": True, "terminal_taxon_id": 1, "authority_edge_split_hex": "02"},
        {"terminal": True, "terminal_taxon_id": 2, "authority_edge_split_hex": "04"},
        {"terminal": True, "terminal_taxon_id": 3, "authority_edge_split_hex": "08"},
    ],
    "gene_ids": ["g0"],
    "bstar_members": [],
}


def primitive(value: dict, terminal: bool, taxon_id: int, split: str) -> None:
    value["primitive_entries"][0] = {
        "terminal": terminal,
        "terminal_taxon_id": taxon_id,
        "authority_edge_split_hex": split,
    }


def mutate(case: str, value: dict) -> None:
    if case == "zero_taxa":
        value["taxon_label_bytes_hex"] = []
    elif case == "empty_taxon_label":
        value["taxon_label_bytes_hex"][0] = ""
    elif case == "duplicate_taxon_label":
        value["taxon_label_bytes_hex"][1] = value["taxon_label_bytes_hex"][0]
    elif case == "wrong_terminal_singleton":
        primitive(value, True, 0, "02")
    elif case == "terminal_out_of_range":
        primitive(value, True, 4, "01")
    elif case == "internal_nonsentinel_id":
        primitive(value, False, 0, "03")
    elif case == "internal_empty_side":
        primitive(value, False, 0xFFFFFFFF, "00")
    elif case == "internal_full_side":
        primitive(value, False, 0xFFFFFFFF, "0f")
    elif case == "internal_larger_side":
        primitive(value, False, 0xFFFFFFFF, "07")
    elif case == "internal_tie_wrong_lex":
        primitive(value, False, 0xFFFFFFFF, "0c")
    elif case == "nonzero_split_padding":
        primitive(value, True, 0, "11")
    else:
        raise ValueError(case)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    cases = (
        "zero_taxa", "empty_taxon_label", "duplicate_taxon_label",
        "wrong_terminal_singleton", "terminal_out_of_range",
        "internal_nonsentinel_id", "internal_empty_side", "internal_full_side",
        "internal_larger_side", "internal_tie_wrong_lex", "nonzero_split_padding",
    )
    rows = ["case\texpected\tobserved\tresult"]
    failures = []
    try:
        baseline = species_authority_digest(BASE).hex()
    except Exception as exc:
        raise SystemExit(f"valid reference baseline rejected: {exc}") from exc
    rows.append(f"valid_baseline\tACCEPT:{baseline}\tACCEPT:{baseline}\tPASS")
    raw_ff = copy.deepcopy(BASE)
    raw_ff["taxon_label_bytes_hex"] = ["ff", "42"]
    raw_ff["primitive_entries"] = [
        {"terminal": True, "terminal_taxon_id": 0,
         "authority_edge_split_hex": "01"},
        {"terminal": True, "terminal_taxon_id": 1,
         "authority_edge_split_hex": "02"},
    ]
    raw_expected = "591b83db63e8100d81f27959db30e3314ff213196cb0fa2f4f18dca3f1f8b838"
    raw_observed = species_authority_digest(raw_ff).hex()
    raw_passed = raw_observed == raw_expected
    rows.append(
        f"raw_ff_golden\t{raw_expected}\t{raw_observed}\t"
        f"{'PASS' if raw_passed else 'FAIL'}"
    )
    if not raw_passed:
        failures.append("raw_ff_golden")
    unicode_ff = copy.deepcopy(raw_ff)
    unicode_ff["taxon_label_bytes_hex"][0] = "c3bf"
    unicode_digest = species_authority_digest(unicode_ff).hex()
    unicode_expected = "64a66e1e08f1a1e52e2802f60a60a66988f15c1a6388c71d843109e5c14aed76"
    unicode_passed = unicode_digest == unicode_expected and unicode_digest != raw_observed
    rows.append(
        f"raw_ff_not_utf8_u00ff\t{unicode_expected}:DIFFERENT\t{unicode_digest}:"
        f"{'DIFFERENT' if unicode_digest != raw_observed else 'EQUAL'}\t"
        f"{'PASS' if unicode_passed else 'FAIL'}"
    )
    if not unicode_passed:
        failures.append("raw_ff_not_utf8_u00ff")
    nul_label = copy.deepcopy(raw_ff)
    nul_label["taxon_label_bytes_hex"][0] = "00"
    nul_expected = "80b2d111bbd254169b2985219f8836c8e83af73d18ce3fd23e051997018c6743"
    nul_observed = species_authority_digest(nul_label).hex()
    nul_passed = nul_observed == nul_expected
    rows.append(
        f"embedded_nul_byte_label\t{nul_expected}\t{nul_observed}\t"
        f"{'PASS' if nul_passed else 'FAIL'}"
    )
    if not nul_passed:
        failures.append("embedded_nul_byte_label")
    for case in cases:
        value = copy.deepcopy(BASE)
        mutate(case, value)
        try:
            species_authority_digest(value)
            observed = "ACCEPT"
        except (KeyError, TypeError, UnicodeError, ValueError):
            observed = "REJECT"
        passed = observed == "REJECT"
        rows.append(f"{case}\tREJECT\t{observed}\t{'PASS' if passed else 'FAIL'}")
        if not passed:
            failures.append(case)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(("\n".join(rows) + "\n").encode("utf-8"))
    if failures:
        raise SystemExit("reference encoder failures: " + ",".join(failures))
    total = len(cases) + 4
    print(json.dumps({"status": "REFERENCE_ENCODER_AUTHORITY_CASES_PASS",
                      "passed": total, "failed": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
