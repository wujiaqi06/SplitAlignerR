# Internal ENGINE002 bindings. These are intentionally not exported.

.engine002_authority <- function(taxon_labels, terminal_taxon_ids,
                                 primitive_splits) {
  cpp_engine002_authority_create(
    as.character(taxon_labels),
    as.integer(terminal_taxon_ids),
    primitive_splits
  )
}

.engine002_plan_encode <- function(authority, pattern_id, retained, states,
                                   primitive_queries) {
  cpp_engine002_plan_encode(
    authority,
    as.double(pattern_id),
    retained,
    as.integer(states),
    primitive_queries
  )
}

.engine002_plan_decode <- function(authority, record) {
  cpp_engine002_plan_decode(authority, record)
}

.engine002_plan_view_snapshot <- function(authority, record) {
  cpp_engine002_plan_view_snapshot(authority, record)
}

.engine002_plan_view_probe <- function(authority, record, primitive_ids,
                                       repeats = 1L) {
  cpp_engine002_plan_view_probe(
    authority, record, as.integer(primitive_ids), as.integer(repeats)
  )
}

.engine002_large_offset_arithmetic_probe <- function(record_bytes,
                                                      pattern_count) {
  cpp_engine002_large_offset_arithmetic_probe(
    as.double(record_bytes), as.double(pattern_count)
  )
}

.engine002_memory_store <- function(authority, pattern_count) {
  cpp_engine002_memory_store_create(authority, as.double(pattern_count))
}

.engine002_disk_store <- function(authority, retained_patterns,
                                  directory, run_store_id,
                                  cache_budget, scratch_budget,
                                  index_budget, metadata_budget,
                                  combined_runtime_bound) {
  cpp_engine002_disk_store_create(
    authority, retained_patterns, as.character(directory),
    as.character(run_store_id), as.double(cache_budget),
    as.double(scratch_budget), as.double(index_budget),
    as.double(metadata_budget), as.double(combined_runtime_bound)
  )
}
