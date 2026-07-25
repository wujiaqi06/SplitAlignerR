#!/usr/bin/env python3
import argparse
import hashlib
from pathlib import Path

EXPECTED = {
    "examples/302mammal/expected/final.fix.na_classified.txt":
        "6da4f14a20802a045f6d7e7794a4f832cfbd9108a8697272992519a9191e1ea7",
    "examples/302mammal/expected/final.free.na_classified.txt":
        "0a69cd10bc2714d6d8419069b9499bb495c5b70769c72c1c89e242a2d699e668",
    "examples/302mammal/expected/fix.matrix_no_fuse.txt":
        "970769cc9d2f3aa2d945c2213e9a57e1f714ffd384628a68fd1cfb262113661c",
    "examples/302mammal/expected/fix.matrix_with_fuse.na_fuse.txt":
        "dd7d48a04c690907d13599f8d571a82555edf130254a1eb55adaff9cf8dedaed",
    "examples/302mammal/expected/fix.matrix_with_fuse.txt":
        "d8da2098d656ef0bc58b153f7cc0899b82f10167bb54dcc9ec221616dac55f1e",
    "examples/302mammal/expected/free.matrix_no_fuse.txt":
        "756282bd3c31e87098feff81a6a3ddb3e1775d93da77a4baf883aaa403a4c0af",
    "examples/302mammal/expected/free.matrix_with_fuse.na_fuse.txt":
        "e4abf12b0de2c5f6044ac8fe94dcfe9849bf4607019b5de3e72c52eba476a390",
    "examples/302mammal/expected/free.matrix_with_fuse.txt":
        "ebb7c928a757620c27f4aa97168f4b679dfbba0eb39ec4bb25e2ff3084a8e0c8",
    "examples/302mammal/expected/species_tree.FigTree.tre":
        "ba7bf85618581065c6d6dbd3d71fbeb4468b4e2a24b4cca47af630f78ff2159d",
    "examples/302mammal/expected/species_tree.branch_map.txt":
        "ec769cd16fb27e93e9f962a4320b95ee56e3de5eb00ee6398bacbe7c3a9edef9",
    "examples/302mammal/expected/species_tree.forSplit.nwk":
        "bb046d5072a6e86841515dd77b76b4b09cb113f22883d181aac63660e530dc68",
    "examples/302mammal/expected/species_tree.splits.txt":
        "e9e2aaf5e8dbb4932c99700a1d74232b90d12252df24f2f1c0d2c4f7bfdea29b",
    "examples/302mammal/input/fix_tree.examples.nwk":
        "8e56c884f6e3851e9a36e8977b36ef20c89ffec8001e76c6506e27384a16f605",
    "examples/302mammal/input/free_tree.examples.nwk":
        "90bdd55ce57b15bc921ee708d3b1bceb4306aa2806a8fbe67338d6aa6e7f71b0",
    "examples/302mammal/input/speciesTree302.nwk":
        "f975e0c22c7817ff1d785f60c39958a28e0827a93e3a46383cbfe3ca497cc70f",
    "examples/preprint_302mammal/input/fix.2275genes.nwk":
        "6bfaa5e134a3bedbd77624134c50855f80f536205ca70d5b0ffe055d7f36b0ab",
    "examples/preprint_302mammal/input/free.2275genes.nwk":
        "cf19a1befac3ffa007f44867e26f1d63e1c732dfe7367f6058dd8a4bff322efb",
    "examples/preprint_302mammal/input/speciesTree302.nwk":
        "f975e0c22c7817ff1d785f60c39958a28e0827a93e3a46383cbfe3ca497cc70f",
}
RESIDUAL_NAME = "01_residual_NA_cell_ledger.tsv"
RESIDUAL_SHA256 = "1927301f1c0cfbcda98714392ac5dfc2f5bf2401ac7031bd8fd5d76ba1734a5e"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--perl-root", required=True)
    parser.add_argument("--residual-dir", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    perl_root = Path(args.perl_root)
    residual = Path(args.residual_dir) / RESIDUAL_NAME
    rows = []
    failed = False
    for relative, expected in EXPECTED.items():
        path = perl_root / relative
        observed = sha256(path) if path.is_file() else "MISSING"
        status = "PASS" if observed == expected else "FAIL"
        failed |= status == "FAIL"
        rows.append((relative, expected, observed, status))
    observed = sha256(residual) if residual.is_file() else "MISSING"
    status = "PASS" if observed == RESIDUAL_SHA256 else "FAIL"
    failed |= status == "FAIL"
    rows.append((f"residual/{RESIDUAL_NAME}", RESIDUAL_SHA256, observed, status))

    report = Path(args.report)
    report.write_text(
        "path\texpected_sha256\tobserved_sha256\tstatus\n"
        + "".join("\t".join(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    if failed:
        raise SystemExit("authority SHA-256 verification failed")


if __name__ == "__main__":
    main()
