# ENGINE002-FIX001B runtime evidence

Runtime data is diagnostic and must not be interpreted as a controlled
cross-platform comparison or an application-level SplitAligner speedup.

## Same-host SHA comparison

The FIX001A base and repaired state machines were compiled with the same
compiler and benchmark driver on the same Apple-arm64 host.

| Case | Bytes | Chunk | Repetitions | Old median | New median | New/old | Digest |
|---|---:|---:|---:|---:|---:|---:|---|
| realistic repeated chunks | 134,217,728 | 18,191 | 7 | 0.723708 s | 0.720912 s | 0.996 | identical and standard |
| pathological one-byte calls | 8,388,608 | 1 | 5 | 0.0310932 s | 0.0801897 s | 2.579 | old wrong; new standard |

The realistic chunk case shows no material primitive regression.  The
pathological one-byte case exposes the cost of per-call invariant preservation
while also demonstrating that the faster old digest was wrong; it is disclosed
rather than averaged into the application workload.

## Local full-authority diagnostic

```text
1,974-plan runs: 18.089, 17.559, 17.760 s
median: 17.760 s
reference precompute: 475.811 s
encode: 2.219 s
decode: 0.685 s
direct view: 1.119 s
re-encode: 2.416 s
memory store build/finalize: 0.487 / 0.006 s
disk store build/finalize/reopen: 0.733 / 2.500 / 1.183 s
random lookup: 0.031 s
authority store bytes: 37,731,172
peak RSS: 577,552,384 bytes
```

Hosted-runner per-platform timings remain diagnostic.  Exact raw values are in
the platform artifacts and normalized runtime CSV.

## Designated-host large stores

```text
2,223,669,984-byte store: build 304.905 s; fresh validation 67.694 s;
  build CPU user/system 295.044/5.494 s; peak RSS 203,276,288 bytes
4,371,260,760-byte store: build 601.052 s; fresh validation 130.233 s;
  build CPU user/system 580.736/11.171 s; peak RSS 238,829,568 bytes
```

Both were regenerated with the corrected digest, independently reconstructed,
fresh-process reopened, and queried at the final record.
