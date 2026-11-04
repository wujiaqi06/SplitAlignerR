Fast C ABI 2 integration in SplitAlignerR

The native integration described below originated in 0.1.0.9004.
Development 0.1.0.9005 adds layered fusion groups in R and supports the
original paired finalizer through rule = "legacy".

Version 0.1.0.9004 replaced the align_branches/validate_species_tree
native matching path with the accepted SplitAlignerFast exact uint64 bitset
core. The public R functions, graph states, paired finalizer, label registry,
and fixed-only exchange schema retain their 9002 contracts.

Source: SplitAlignerR 0.1.0.9002 tar SHA256
c4fcc16cce3aaf90189a686b57dd0eadba2d20fccfd246d42deeef353f83522f
Fast source commit: 4f2d0c699a62d45b4dd3fc44999e2e134f0cd9dc.
The four vendored native source/header files are byte-identical to that source.
See SOURCE_LOCK.json and API.txt. No external Fast executable or OpenSSL is
needed by this R adapter. Normal R/Rcpp/ape/digest dependencies still apply.

Implementation: parse each input once, use shared taxon IDs, retain original
postorder node source IDs, then create Reference/Coverage/Mapping via C ABI 2.
Coverage cache: 64 entries FIFO, exact full-bitset keys local to one Reference.
Display strings are converted once per prepared coverage and retained by protected
R vectors for each gene; cells refer to projection indices. Native cache eviction
does not invalidate these display vectors. Gene-ID byte keys are deduplicated
without transcoding or changing their byte-based identity rules.
Native axis IDs are permuted back to the existing B axis; composite members and
ledger presentation order remain unchanged. String canonical keys are rendered
for existing public outputs; they do not decide native split identity.
All three apply families are checked, including unmatched gene edges. R still
exports the same fields; this migration adds no unmatched-return extension.
Native matching and aggregation errors include the failing gene ID. Recursion depth is limited to 4096; an
oversized tree is rejected explicitly. Checkpoints allow R user interruption.

Identity: package 0.1.0.9004, core 0.2.0-fast-abi2, unchanged schema1.0.0.
Results declare backend name/ABI/Fast source commit. The object validator checks
these values against the compiled backend. Legacy results can be inspected with
read_splitaligner_result(..., check_version=FALSE), without relabelling them.
Old/new mixed pairing is rejected. Exchange files correctly carry the new
producer identity and content seals; external consumers need their own explicit
compatibility decision, never a forged old version.

Use splitaligner_core_info() to inspect the installed backend. API.txt describes
the native mapping contracts used by the adapter, and SOURCE_LOCK.json lists
the exact upstream implementation files.

The four files listed in SOURCE_LOCK.json are distributed under the MIT
License in this directory. SplitAlignerR is distributed under GPL-3.
