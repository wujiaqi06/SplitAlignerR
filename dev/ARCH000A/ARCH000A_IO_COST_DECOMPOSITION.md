# ARCH000A I/O and CPU cost decomposition

## Principle

Sequential input time is not called I/O when it includes tokenization, pattern
construction or graph truth. ARCH000A records storage reads separately from CPU
work.

## First-pass isolated components

The authority decomposition runs the following phases independently:

1. raw sequential read;
2. tree-boundary and optional gene-ID detection;
3. tip-label tokenization;
4. taxon-name to integer-ID mapping;
5. exact bitset and pattern-key construction;
6. exact registry lookup and canonical unique collection;
7. one S9 truth-plan construction per unique pattern;
8. exact B-star member-set emission;
9. chunk-local B-star sort/unique;
10. deterministic global merge-union.

This repeated-phase measurement deliberately materializes intermediate values
to isolate costs. Its phase sum is not substituted for the normal streaming
pipeline wall time.

The packed catalog benchmark separately records combined fixed/free scan time,
truth construction, packing and physical writing. This distinguishes CPU truth
construction from storage output.

## Second-pass instrumented components

The selected packed-disk-plus-LRU pipeline records:

1. an independent raw sequential-read control;
2. ape Newick parse;
3. empirical split-index construction;
4. packed truth load/cache access and decode;
5. deterministic split queries;
6. compact matrix or checksum-sink write;
7. branch-counter update.

The raw control is an additional read used only to quantify storage. Instrumented
phase times occur inside the scientific processing pass.

## Packed-store throughput

Write throughput uses complete packed file bytes divided by measured write time.
Cold record throughput uses verified bytes returned from the file divided by
read time. Decode time is reported separately. Warm packed-LRU hits do not count
as disk bytes.

## Storage sensitivity

Measurements apply to the available internal APFS SSD only. No HDD, network
filesystem or cloud object-store result is fabricated. The adaptive production
design should stage immutable remote input/store files to local scratch, verify
their SHA-256, execute both passes, and publish evidence before cleanup.

## Temporary file lifecycle

Benchmark stores live only under the explicit runner work directory. Successful
cases write compact metrics and then remove disposable stress stores. The shared
authority store remains only until the full benchmark matrix and conformance
run complete, then is removed. The handoff ZIP contains generation commands,
format definition, hashes and measurements, not large disposable inputs.

## B-star compaction time

Large-tree B-star stress separates member-set emission from local sort/unique
and global sorted-union time. The report gives the compaction fraction of the
measured stress pipeline. A 100,000-locus projected row does not imply that
global union remains linear; it explicitly withholds projected peak RSS and
unique-coordinate growth.
