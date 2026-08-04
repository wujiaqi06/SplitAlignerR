# ENGINE002-FIX001B Pro RECERT checklist

## Intake and identity

- [ ] Verify all outer SHA-256 sidecars before extraction.
- [ ] Reject duplicate members, absolute paths, traversal, and symlinks.
- [ ] Verify every internal `SHA256SUMS` entry.
- [ ] Verify the complete Git bundle and exact final head/tree.
- [ ] Verify ancestry from ENGINE001 through FIX001B without squash/amend.
- [ ] Confirm `v0.1.0` still peels to the certified commit.
- [ ] Authenticate byte-identical Pro original decision, MRE, output, checker,
      certificate, and reviewed FIX001A artifacts.

## Standards compliance

- [ ] Independently compile and run Pro's exact MRE.
- [ ] Independently verify the fixed public SHA-256 vectors.
- [ ] Inspect/rerun all 34,191 two-part cases; require zero mismatch.
- [ ] Inspect/rerun the frozen-seed 10,000 multipart cases; require zero
      mismatch.
- [ ] Confirm expected digests come from an independent standard
      implementation, not production one-shot SHA alone.
- [ ] Confirm zero-length/null, partial-block, multi-block, repeated digest,
      and continuation contracts.

## Durable store

- [ ] Independently reconstruct the corrected two-record golden aggregate.
- [ ] Confirm footer bytes 48--79 equal standard SHA-256.
- [ ] Confirm the maintained checker validates canonical record geometry and
      does not call package hashing code.
- [ ] Confirm the old defective 906-byte store is preserved and rejected.
- [ ] Confirm aggregate-only and payload-mutation fixtures rebuild enclosing
      non-target hashes yet are rejected at the aggregate layer.
- [ ] Confirm footer-only mutation reaches the ordinary footer checksum.
- [ ] Confirm >2 GiB and >4 GiB stores were rebuilt at the exact production
      implementation, independently aggregated, reopened, and final-record
      queried.

## Replay and boundaries

- [ ] Authenticate Linux, macOS, and Windows artifacts from the final run.
- [ ] Confirm build, check, installed tests, and mandatory package gates pass
      on all three release platforms.
- [ ] Confirm exact golden and authority deterministic bytes across platforms.
- [ ] Confirm all 1,974 authority plans and every listed invariant pass.
- [ ] Confirm R/XPtr lifecycle, corruption, no-replace, Windows binary/u64,
      and fault-cleanup gates.
- [ ] Confirm package/Rcpp ASan and UBSan replay at the corrected commit.
- [ ] Treat hosted-runner runtimes as diagnostic only.
- [ ] Confirm no public export, schema version, scientific semantics, package
      version, release metadata, or certified tag changed.

## Verdict

Issue exactly one independent verdict for the exact frozen object:

```text
PASS
FAIL
INCOMPLETE
```
