.sx_migration_body <- function(migration) migration[setdiff(names(migration), "migration_id")]
.sx_check_migration <- function(migration, tree_hash, branch_hash, previous, scheme, synthetic) {
  .sx_fields(migration, c("schema_version", "from_scheme", "to_scheme", "reference_tree_sha256",
                          "ordered_branch_ledger_sha256", "from_ledger", "to_ledger", "authority", "migration_id"), "migration")
  .sx_scheme(migration$from_scheme); .sx_scheme(migration$to_scheme)
  .sx_need(identical(migration$schema_version, .sx_version) &&
             identical(migration$migration_id, paste0("label-migration2:", .sx_hash(.sx_migration_body(migration)))), "migration identity mismatch")
  .sx_need(identical(migration$reference_tree_sha256, tree_hash) &&
             identical(migration$ordered_branch_ledger_sha256, branch_hash), "wrong tree or ordered branch ledger for migration")
  .sx_need(identical(migration$from_scheme, scheme) && identical(migration$from_ledger, previous),
           "wrong source scheme/ledger or already migrated input")
  .sx_need(!identical(migration$from_scheme, migration$to_scheme), "migration must change the explicit alias scheme")
  columns <- c("coordinate_id", "alias", "scheme_id", "scheme_version")
  for (pair in list(list(migration$from_ledger, migration$from_scheme), list(migration$to_ledger, migration$to_scheme))) {
    ledger <- pair[[1L]]; scope <- pair[[2L]]
    .sx_need(is.data.frame(ledger) && identical(names(ledger), columns) &&
               .sx_keys(ledger$coordinate_id) && .sx_keys(ledger$alias) &&
               all(grepl("^B[1-9][0-9]*$", ledger$alias)) &&
               all(ledger$scheme_id == scope$id) && all(ledger$scheme_version == scope$version), "invalid scoped label ledger")
  }
  .sx_need(identical(migration$from_ledger$coordinate_id, migration$to_ledger$coordinate_id), "migration cannot change coordinate identities or their order")
  authority <- migration$authority
  .sx_need(is.list(authority) && .sx_string(authority$kind), "unknown migration provenance")
  if (identical(authority$kind, "synthetic_fixture")) {
    .sx_fields(authority, c("kind", "id", "definition"), "synthetic authority")
    .sx_need(synthetic && .sx_string(authority$id) && .sx_string(authority$definition),
             "synthetic migration requires an explicitly synthetic producer and opt-in")
  } else if (identical(authority$kind, "source_bound_profile")) {
    .sx_validate_legacy_authority(authority, migration)
  } else .sx_need(FALSE, "unknown migration authority; a derived crosswalk is not independent historical authority")
  invisible(migration)
}

.sx_validate_label_history <- function(x) {
  .sx_scheme(x$labels$active_scheme)
  previous <- x$labels$native_ledger; scheme <- x$labels$native_scheme
  seen <- character()
  .sx_need(is.list(x$labels$migrations), "migration history must be a list")
  for (migration in x$labels$migrations) {
    .sx_need(!migration$migration_id %in% seen, "duplicate migration operation")
    .sx_check_migration(migration, .sx_hash(x$tree$phylo), .sx_hash(x$coordinates), previous, scheme,
                        synthetic = identical(x$producer$source$provenance_status, "synthetic_fixture"))
    seen <- c(seen, migration$migration_id); previous <- migration$to_ledger; scheme <- migration$to_scheme
  }
  .sx_need(identical(previous, x$labels$active_ledger) && identical(scheme, x$labels$active_scheme),
           "active label scheme/ledger lacks an exact migration provenance chain")
  invisible(x)
}

#' Construct an explicitly scoped branch alias migration
#' @param x A validated exchange envelope to bind as source.
#' @param to_scheme Registered target scheme list(id, version).
#' @param target_aliases Target aliases in the existing coordinate order.
#' @param authority Explicit synthetic or accepted source-bound profile authority.
#' @param allow_synthetic Must be TRUE for synthetic fixture migrations.
#' @return A migration bound to the exact tree and ordered coordinate/label ledgers.
#' @export
new_splitaligner_label_migration <- function(x, to_scheme, target_aliases, authority, allow_synthetic = FALSE) {
  validate_splitaligner_exchange(x); .sx_scheme(to_scheme)
  if (identical(authority$kind, "synthetic_fixture"))
    .sx_need(isTRUE(allow_synthetic), "synthetic migration requires explicit allow_synthetic=TRUE")
  migration <- list(schema_version = .sx_version, from_scheme = x$labels$active_scheme, to_scheme = to_scheme,
                    reference_tree_sha256 = x$identity$reference_tree_sha256,
                    ordered_branch_ledger_sha256 = x$identity$ordered_branch_ledger_sha256,
                    from_ledger = x$labels$active_ledger,
                    to_ledger = .sx_label_ledger(x$coordinates, to_scheme, target_aliases), authority = authority)
  migration$migration_id <- paste0("label-migration2:", .sx_hash(migration))
  .sx_check_migration(migration, x$identity$reference_tree_sha256, x$identity$ordered_branch_ledger_sha256,
                      x$labels$active_ledger, x$labels$active_scheme,
                      identical(x$producer$source$provenance_status, "synthetic_fixture") && isTRUE(allow_synthetic))
  migration
}

#' Apply a checked scoped alias migration without changing scientific coordinates
#' @param x A validated exchange envelope.
#' @param migration A bound migration object.
#' @param allow_synthetic Must be TRUE for synthetic fixture migrations.
#' @return An envelope with new active label metadata and preserved original result.
#' @export
migrate_splitaligner_labels <- function(x, migration, allow_synthetic = FALSE) {
  validate_splitaligner_exchange(x)
  ids <- vapply(x$labels$migrations, `[[`, character(1), "migration_id")
  .sx_need(!migration$migration_id %in% ids, "duplicate migration operation")
  .sx_check_migration(migration, x$identity$reference_tree_sha256, x$identity$ordered_branch_ledger_sha256,
                      x$labels$active_ledger, x$labels$active_scheme,
                      identical(x$producer$source$provenance_status, "synthetic_fixture") && isTRUE(allow_synthetic))
  x$labels$active_scheme <- migration$to_scheme; x$labels$active_ledger <- migration$to_ledger
  x$labels$migrations <- c(x$labels$migrations, list(migration))
  x$identity$ordered_label_ledger_sha256 <- .sx_hash(x$labels$active_ledger)
  x$annotation <- .sx_tree_map(x$tree$phylo, x$coordinates, x$labels$active_ledger)
  x <- .sx_seal(x); validate_splitaligner_exchange(x); x
}

# Source-bound authority validation lives in exchange-legacy.R. Generic or
# crosswalk-derived claims are never promoted to that authority class.
