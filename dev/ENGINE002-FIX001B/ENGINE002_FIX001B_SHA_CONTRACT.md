# ENGINE002-FIX001B SHA contract

The implementation is SHA-256 as standardized by FIPS 180-4.  No domain
specific or producer-defined digest is accepted.

## State transitions

For every externally reachable state:

```text
0 <= buffered_ <= 63
buffered_ == total_ modulo 64
```

`update(data, size)` counts exactly `size` bytes.  A pre-existing partial block
is appended to, retained if incomplete, or compressed exactly once when it
reaches 64 bytes.  Further complete blocks are compressed directly and the
final 0--63 bytes are retained.  Total byte-count addition is checked and the
digest path rejects a byte count larger than `UINT64_MAX / 8` before converting
to the 64-bit SHA bit length.

## Pointer and digest behavior

```text
update(nullptr, 0)                 accepted
update(nullptr, nonzero)           typed invalid_argument
repeated digest()                  identical bytes
digest() then later update()       preserves the pre-digest state contract
digest()                           does not mutate the live state
```

## Independent standard evidence

Fixed expected vectors cover the empty message, `a`, `abc`, the FIPS
multi-block vector, and one million `a` bytes.  Every vector is exercised as a
one-shot update, one-byte updates, irregular partitions, and partitions with
zero-length calls.  Python `hashlib.sha256` is the independent oracle for the
exhaustive and randomized partition differential.

The production one-shot implementation is checked but is not treated as the
only oracle.  Pro's original MRE is preserved byte-identically and compiled
against the repaired source.
