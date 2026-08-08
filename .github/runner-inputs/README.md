# Temporary ENGINE003 Windows runner input

This branch and its draft PR are orchestration-only and must never be merged.

The adjacent ZIP is the byte-identical frozen replay input reviewed by main
control:

```text
SplitAlignerR_ENGINE003_VALIDATION_XPLAT_REPLAY_2781929_20260807_JST.zip
SHA-256:
240f6309463f081c41c368fd652a516160584c104623a62bbb61638d92b682da
```

The reviewed sibling `.sha256` sidecar is included unchanged.

The workflow verifies this outer hash and all 93 package-manifest entries
before execution. It then runs the unchanged package on `windows-latest`,
verifies the five raw outputs, and uploads them with separate runner/command
context. It makes no Windows durability claim.

Candidate commit `f2a9adf8ff5f2a5a15bd7af1a1db1cd1a612b440`, its branch,
and `main` are not modified by this runner-only branch.
