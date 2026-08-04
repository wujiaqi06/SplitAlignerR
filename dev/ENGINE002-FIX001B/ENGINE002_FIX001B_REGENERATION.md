# ENGINE002-FIX001B regeneration

All durable fixtures derived from the defective incremental aggregate were
regenerated through the corrected production builder.  Expected digests were
not hand-patched.

Corrected deterministic identities:

```text
golden plan SHA-256:
c1e3167bdb3f2e9fbd08276bd224ce63b771edb7ef8341338d6088935ccecda3

golden store component SHA-256:
d031f36ba4895e67ef03e46ba653ccbe92e23b8389d5a812a657b6fab30f765e

golden manifest SHA-256:
e2a8729f1d39865c202a4c028459edcbe909e7eb0084893d9aefb939b19b5b40

authority record stream SHA-256:
d64449e5469b709d6596a2309d996363497a9b971f0319f038630c3025e5e4f3

authority component SHA-256:
b4d3e77ff2c770a252e180820fc7fcacfb5f8bbd2480962a4cdbe230d65f0e7

authority manifest SHA-256:
7c7d77729bbf6228d71bfa5237aed8763b0638f8dc88514ea8737167851d3a40
```

Truth-plan record bytes, decoded scientific authority objects, state classes,
fiber/member sets, coordinate identity, and plan identity are unchanged.  The
intended durable differences are only the standard payload aggregate and
enclosing bytes/hashes derived from it.

The defective 906-byte store is preserved only as
`tests/testthat/fixtures/engine002/history/fix1a_bad_aggregate.bin`; it is not
relabeled or accepted as a current golden fixture.
