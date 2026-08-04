# ENGINE002-FIX001B partition differential

Independent oracle: Python `hashlib.sha256`.

Frozen seed:

```text
0x5a17b001
```

Results:

```text
fixed public-vector forms: 15
fixed-vector mismatches: 0
Pro exact abc MRE: PASS
two-part message lengths: 0..260
two-part cases: 34,191
two-part mismatches: 0
random multipart cases: 10,000
random maximum message bytes: 65,536
random multipart mismatches: 0
```

Boundary evidence records every split for lengths 0, 1, 2, 55, 56, 57, 62,
63, 64, 65, 66, 119, 120, 121, 126, 127, 128, 129, 130, 191, 192, 193, 255,
256, and 257.  Random partitions include one-byte calls, long calls,
alternating small/large calls, zero-length calls, and partitions crossing both
padding and compression boundaries.  Repeated `digest()` and continuation
after `digest()` are also covered.

The maintained driver and all raw normalized results are under `independent/`
and `evidence/`; neither imports or calls package hashing code for its expected
digest.
