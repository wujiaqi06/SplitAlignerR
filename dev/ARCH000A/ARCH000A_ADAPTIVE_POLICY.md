# ARCH000A adaptive truth-store policy

## Inputs

The experimental selector records:

- locus count;
- unique retained-pattern count and fraction;
- measured verbose full-cache estimate;
- measured or exact-formula packed full-cache estimate;
- configured cache and whole-process budgets;
- mean S9 reconstruction seconds per plan;
- packed record/store bytes;
- measured local write/read throughput;
- observed or order-modelled LRU hit rate;
- storage availability and validation status.

Every recommendation includes these inputs and a textual rationale.

## Decision

Retain-all packed memory is considered only when the packed complete-cache
estimate is no more than 80% of its assigned cache budget. The verbose R-plan
estimate is recorded separately and never substituted for packed bytes.

If the estimate exceeds budget and validated local scratch is available, select:

    packed disk store + byte-budgeted packed-body LRU

If validated storage is unavailable, select:

    recompute on demand + byte-budgeted verbose-plan LRU

The no-storage fallback accepts CPU cost rather than weakening the memory bound
or scientific semantics.

## Budget selection

The planner first reserves measured/projected bytes for pattern registry,
B-star registry, empirical scratch, counters, and output mode. It then assigns
only the remaining safe portion to the truth-store cache. A 2 GiB machine may
therefore receive a 32 or 64 MiB packed cache even if a 256 MiB value was faster
on the development machine.

## Locality

Original, reversed, grouped, maximally interleaved and fixed-seed random orders
are measured. The planner does not assume a high hit rate from average pattern
frequency. Grouping may improve locality for a file-backed batch export, but
public gene order and normalized output remain canonical and unchanged.

## Slow storage

If sampled local-equivalent read throughput is poor, compare:

    one-time reconstruction cost
    versus
    cold packed-record reload cost

A larger packed cache is allowed only inside the configured budget. Recompute
is chosen when storage reload is slower or unavailable. Remote staging must be
explicit and checksummed.

## Non-public status

This selector is a development evidence tool. It does not add a package option,
silently select a public execution path, or infer fixed/free provenance.
