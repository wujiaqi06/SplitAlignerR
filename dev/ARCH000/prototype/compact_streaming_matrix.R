## Compact two-pass engine entrypoint.  Implementation is shared in
## arch000_common.R to keep conformance and benchmark paths identical.

arch_compact_align_file <- function(species_tree, gene_tree_file,
                                    first_method = "taxa_scan",
                                    bstar_threshold_bytes = 32 * 1024^2) {
  arch_stream_compact(
    species_tree,
    gene_tree_file,
    first_method = first_method,
    bstar_threshold_bytes = bstar_threshold_bytes
  )
}
