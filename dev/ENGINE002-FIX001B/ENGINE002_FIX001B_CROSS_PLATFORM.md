# ENGINE002-FIX001B cross-platform replay

Final implementation object:

```text
commit: 9588400014a65170bc7dbb718817d9f258237f9d
tree:   ecf4476e484980fdf27c6787b8ca968105c3e253
run:    30890940707
run conclusion: SUCCESS
comparison job: 91946302927 (SUCCESS)
```

## Mandatory release platforms

| Platform | Job | Package build/check | Installed suite | SHA differential | Authority |
|---|---:|---|---|---|---|
| Ubuntu R release | 91932591141 | `Status OK` | 1,017 expectations, 0 failure/error | 15 vectors, 34,191 two-part, 10,000 multipart; 0 mismatch | 1,974/1,974 |
| macOS R release | 91932591145 | `Status OK` | 1,017 expectations, 0 failure/error | 15 vectors, 34,191 two-part, 10,000 multipart; 0 mismatch | 1,974/1,974 |
| Windows R release | 91932591091 | `Status OK` | 1,017 expectations, 0 failure/error | 15 vectors, 34,191 two-part, 10,000 multipart; 0 mismatch | 1,974/1,974 |

The Linux R-devel advisory job `91932591122` also completed successfully with
`R CMD check: Status OK`; it is supplemental rather than a mandatory release
platform.

All three platforms retained the two exact allowlisted `scipen` warnings and
five disclosed non-ENGINE002 skips.  These are test outcomes, not package-check
warnings or errors.

## Exact deterministic comparison

The frozen comparison requires byte-for-byte equality, without normalization,
for the corrected golden plan, store and manifest, and for the 1,974-plan
authority store and manifest.  It also requires equal payload aggregates,
stress-store hashes, R-boundary results, and the Windows binary/u64/no-replace
gates.  All comparisons passed.

```text
golden plan:      c1e3167bdb3f2e9fbd08276bd224ce63b771edb7ef8341338d6088935ccecda3
golden store:     d031f36ba4895e67ef03e46ba653ccbe92e23b8389d5a812a657b6fab30f765e
golden manifest:  e2a8729f1d39865c202a4c028459edcbe909e7eb0084893d9aefb939b19b5b40
golden aggregate: 86fc58c3816a0b2424d9bdaf1f1b3f93744e6e3ab6ed31e04b2ab138d617fa73
authority stream: d64449e5469b709d6596a2309d996363497a9b971f0319f038630c3025e5e4f3
authority store:  b4d3e77ff2c770a252e180820fc7fcacfb5f8bbd2480962a4cdbe230d65f0e7
authority manifest: 7c7d77729bbf6228d71bfa5237aed8763b0638f8dc88514ea8737167851d3a40
authority aggregate: c3e997e7acb49960aa7022b698a7cf0fac1c2ad0603c40f0d5c3459cac69736e
```

The Windows job additionally rebuilt and reopened a 158,360,976-byte physical
store with 10,000 patterns and queried its last record.  Binary mode, no CRLF
translation, 64-bit offsets, no C `long` truncation, and atomic no-replace
publication all passed.

Hosted-runner timings are diagnostic only and are not a controlled performance
comparison.
