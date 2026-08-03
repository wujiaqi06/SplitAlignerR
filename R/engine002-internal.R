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

