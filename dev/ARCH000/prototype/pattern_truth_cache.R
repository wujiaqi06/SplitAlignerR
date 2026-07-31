arch_pattern_cache_demo <- function(species_tree, gene_newicks) {
  authority <- arch_species_authority(species_tree)
  taxa <- lapply(gene_newicks, arch_scan_tips)
  retained <- lapply(taxa, arch_taxa_to_ids, authority = authority)
  keys <- vapply(retained, arch_pattern_key, character(1))
  canonical_keys <- sort(unique(keys), method = "radix")
  plans <- lapply(canonical_keys, function(key) {
    arch_build_truth_plan(authority, retained[[match(key, keys)]])
  })
  names(plans) <- sprintf("P%08d", seq_along(plans))
  list(
    gene_to_pattern = match(keys, canonical_keys),
    pattern_keys = canonical_keys,
    plans = plans,
    truth_construction_count = length(plans)
  )
}
