# ENGINE002-FIX001B store aggregate

The maintained Python checker parses `TruthPlanStore-v1.0`, validates canonical
record geometry and non-aggregate checksums, and reconstructs exactly:

```text
"SplitAlignerR/TruthPlanPayloadAggregate/v1\0"
record_count:u64 little-endian
for pattern_id = 0..record_count-1:
    pattern_id:u64 little-endian
    payload_length:u64 little-endian
    exact payload bytes
```

It computes the aggregate with Python `hashlib.sha256` and compares it with
footer bytes 48--79.  It does not call the package SHA implementation or trust
builder/validator intermediate hashes.

Measured corrected aggregates:

| Store | Records | Canonical bytes | Standard aggregate | Match |
|---|---:|---:|---|---|
| golden | 2 | 189 | `86fc58c3816a0b2424d9bdaf1f1b3f93744e6e3ab6ed31e04b2ab138d617fa73` | PASS |
| authority | 1,974 | 37,351,831 | `c3e997e7acb49960aa7022b698a7cf0fac1c2ad0603c40f0d5c3459cac69736e` | PASS |
| streaming stress | 1,000 | 15,607,419 | `d5bbb3d7b929a9aca4e997dcf1adead063144042cb7f598de7cc2d1c62e59950` | PASS |
| >2 GiB | 140,000 | 2,196,789,651 | `b4c843de4d704eccb7979a5f725c32e2463ab6241bf8c951338bd01667718eec` | PASS |
| >4 GiB | 275,000 | 4,318,460,427 | `4b6b78b65502572b21c8c7aa2c496eefa158844e3595dd4d825d34b7cc673afb` | PASS |

The large-store checker uses a read-only memory map plus one-record bounded
payload slices.  Serialization and production reopen validation are separate
from this independent standard aggregate reconstruction.

The 906-byte FIX001A development store is retained under `history/` and has
stored defective aggregate
`975494a2e4eb726a3111a2e41d48e2fac3271adaa1c0499fc31e29aa8806ccf9`.
The corrected validator rejects it at the payload-aggregate layer.

The aggregate-only fixture changes the aggregate field while rebuilding all
enclosing non-target hashes and its manifest.  It is rejected specifically as
a payload aggregate mismatch.  Payload mutation with rebuilt enclosing hashes
reaches the same layer; a footer-only mutation reaches the footer checksum
first, as designed.
