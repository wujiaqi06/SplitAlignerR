# Algorithm S3: reference-only truth tables

`reference_truth()` takes one reference tree and a list of retained-taxon sets.
It accepts no empirical gene trees. The graph operations share tested pruning
and contraction helpers with S4, while the rooted restriction policy is explicit.

1. Parse the reference and freeze its input-local primitive B aliases. Normalize
   degree-two representation aliases before freezing unrooted coordinates; keep
   the original rooted child edges distinct.
2. For each retained set, prune excluded leaves and dangling internal vertices.
   In rooted mode protect the original root and retain the complete path from
   it to every surviving taxon. Contract non-root degree-two nodes while carrying
   all original members and reference source edges. In unrooted mode no display
   root is protected.
3. Classify original members: absent members are `NA_struct`, members of a
   multiple-member current edge are `NA_fuse`, and separately represented members
   are `observed`. No empirical recovery or topology-discordance state is inferred.
4. Only after graph structure is fixed, derive expected measurements from the
   complete original reference sources. If any source length is unavailable,
   the component's expected length is unavailable; never use a partial sum.
5. Keep the original numeric matrix separate from the shared fusion matrix.
   Define shared columns from actual current fusion groups. `direct` fills
   active groups only; `whole` also accepts exact unions of complete current
   reference components with available expected lengths. Preserve sources and
   construction modes without changing original-member states.

For rooted singleton sets, the original root-to-tip path remains. Empty sets
have no edges. Unrooted sets of zero or one taxon have no edges. At least two
taxa are required in the initial reference tree. Every internal node in that
original input, including its root, must have at least two children. This
retains the 0.1.0.9009 reference-input contract. A unary original root created
by restriction is a valid S3 result and remains protected; it does not imply
that an already unary original reference is accepted. S4's separate allowance
for explicit unary gene stems does not broaden S3 reference inputs.

S3 and the S4 reference layer both record `original_root_preserved` in rooted
mode. S4 may remove the stem or contract root-adjacent edges in a separate
unrooted matching view, but those operations do not rewrite the reference
states or deletion-fusion members. An unrepresented stem receives no empirical
measurement. A joint observation remains distinct from a deletion fusion.

The historical S4 0.1.0.9007--0.1.0.9009 rooted/MRCA convention was different:
it discarded ancestral-stem members. Those artifacts and their explicitly
historical tests remain preserved; they do not define the new S4 reference
layer. The original rooted/global Catnip10 stem cells and fused groups continue
to belong in S3 truth unchanged.

The regular mapping default remains split-based `align_branches()` (S2/Fast),
even in fixed mode. S3 truth and S4 alignment are explicitly selected tools.
`recompute_catnip10_oracle()` and its frozen unrooted data remain unchanged.

Table 5 can describe the R package as: “Split-based mapping by default
(Algorithm S2), rooted and unrooted reference-truth construction (Algorithm S3),
and optional fixed-topology graph alignment (Algorithm S4).” Mention the local
candidate version until this implementation is published.
