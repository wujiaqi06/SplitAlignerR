# Temporary ENGINE003 XPLAT FIX001 Windows successor input

This branch and its draft PR are orchestration-only and must never be merged.

The adjacent ZIP is the byte-identical frozen successor replay authorized by
main control for exactly one unchanged Windows execution:

```text
SplitAlignerR_ENGINE003_XPLAT_FIX001_REPLAY_3b7cb92_20260808_JST.zip
SHA-256:
be17a6438da5d16e6960e45fd59c27fa7d1c6441f5311a1145001bbe6f39c1fd
```

The sibling sidecar is included unchanged. The workflow verifies the outer
hash, archive safety, and all 100 internal manifest rows before it executes the
three frozen commands exactly once on `windows-latest`. Complete outputs,
console logs, runner/runtime identity, command identity, and hashes are uploaded
even if execution fails.

The candidate commit, candidate branch, production source, fixtures, and
`main` are not modified or executed by this runner-only branch. Stage-A timing
is not run. This portable replay cannot establish Windows durability.
