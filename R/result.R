build_coordinate_table <- function(result) {
  primitive <- result$primitive_coordinates
  primitive_table <- data.frame(
    coordinate_id = primitive$coordinate_id,
    coordinate_type = "primitive",
    branch_type = primitive$branch_type,
    canonical_reference_split = primitive$canonical_split,
    member_count = 1L,
    member_text = primitive$coordinate_id,
    representation_alias_text = primitive$primitive_alias_text,
    primitive_members = I(lapply(primitive$coordinate_id, function(id) id)),
    stringsAsFactors = FALSE,
    check.names = FALSE
  )

  composite <- result$composite_coordinates
  if (!nrow(composite)) {
    return(primitive_table)
  }
  composite_table <- data.frame(
    coordinate_id = composite$coordinate_id,
    coordinate_type = "composite",
    branch_type = "composite",
    canonical_reference_split = NA_character_,
    member_count = composite$member_count,
    member_text = composite$member_text,
    representation_alias_text = NA_character_,
    primitive_members = I(composite$primitive_members),
    stringsAsFactors = FALSE,
    check.names = FALSE
  )
  out <- rbind(primitive_table, composite_table)
  rownames(out) <- NULL
  out
}

result_invariant_error <- function(message) {
  stop(sprintf("Result object invariant failed: %s", message), call. = FALSE)
}

require_result_columns <- function(table, columns, component) {
  if (!is.data.frame(table)) {
    result_invariant_error(sprintf("`%s` must be a data frame.", component))
  }
  missing <- setdiff(columns, names(table))
  if (length(missing)) {
    result_invariant_error(sprintf(
      "`%s` is missing column(s): %s.",
      component, paste(missing, collapse = ", ")
    ))
  }
  invisible(TRUE)
}

numeric_vectors_equal <- function(left, right) {
  isTRUE(all.equal(
    as.numeric(left), as.numeric(right),
    check.attributes = FALSE, tolerance = 0
  ))
}

retained_taxa_key <- function(taxa) {
  taxa <- enc2utf8(taxa)
  paste0(
    "RT1:", length(taxa),
    paste0(":", nchar(taxa, type = "bytes"), ":", taxa, collapse = "")
  )
}

validate_splitaligner_result_object <- function(result,
                                                check_version = TRUE) {
  if (!inherits(result, "splitaligner_result") || !is.list(result)) {
    stop("Object must inherit from `splitaligner_result`.", call. = FALSE)
  }
  required <- c(
    "state_matrix", "numeric_matrix", "state_ledger",
    "primitive_coordinates", "composite_coordinates", "composite_ledger",
    "gene_provenance", "diagnostics", "species_tree", "conventions",
    "metadata", "coordinate_table", "input"
  )
  missing <- setdiff(required, names(result))
  if (length(missing)) {
    stop(
      sprintf("Result object is missing required component(s): %s.",
              paste(missing, collapse = ", ")),
      call. = FALSE
    )
  }

  if (!is.matrix(result$state_matrix) ||
      !is.character(result$state_matrix)) {
    result_invariant_error("`state_matrix` must be a character matrix.")
  }
  if (!is.matrix(result$numeric_matrix) ||
      !is.numeric(result$numeric_matrix)) {
    result_invariant_error("`numeric_matrix` must be a numeric matrix.")
  }
  genes <- rownames(result$state_matrix)
  if (is.null(genes) || !length(genes) || anyNA(genes) ||
      any(!nzchar(genes)) || anyDuplicated(genes)) {
    result_invariant_error(
      "the state matrix must have unique, nonempty gene row names."
    )
  }
  if (!identical(genes, rownames(result$numeric_matrix))) {
    result_invariant_error(
      "state and numeric matrices have inconsistent gene axes."
    )
  }

  require_result_columns(
    result$primitive_coordinates,
    c(
      "coordinate_id", "canonical_split", "branch_type",
      "primitive_alias_text", "side_a_size", "side_b_size",
      "side_a_taxa", "side_b_taxa", "primitive_aliases"
    ),
    "primitive_coordinates"
  )
  primitive_ids <- as.character(result$primitive_coordinates$coordinate_id)
  if (!length(primitive_ids) || anyNA(primitive_ids) ||
      any(!nzchar(primitive_ids)) || anyDuplicated(primitive_ids)) {
    result_invariant_error(
      "primitive coordinate IDs must be unique and nonempty."
    )
  }
  if (!identical(colnames(result$state_matrix), primitive_ids)) {
    result_invariant_error(
      "the state matrix does not match the primitive coordinate axis."
    )
  }
  if (anyNA(result$primitive_coordinates$canonical_split) ||
      anyDuplicated(result$primitive_coordinates$canonical_split)) {
    result_invariant_error("primitive canonical splits must be unique.")
  }
  if (any(!result$primitive_coordinates$branch_type %in%
          c("terminal", "internal"))) {
    result_invariant_error("primitive branch types are invalid.")
  }

  require_result_columns(
    result$composite_coordinates,
    c(
      "coordinate_id", "coordinate_type", "member_count", "member_text",
      "primitive_members"
    ),
    "composite_coordinates"
  )
  composite_ids <- as.character(result$composite_coordinates$coordinate_id)
  if (anyNA(composite_ids) || any(!nzchar(composite_ids)) ||
      anyDuplicated(composite_ids) || any(composite_ids %in% primitive_ids)) {
    result_invariant_error(
      "composite coordinate IDs must be unique, nonempty, and disjoint from primitives."
    )
  }
  if (length(composite_ids)) {
    if (any(result$composite_coordinates$coordinate_type != "composite")) {
      result_invariant_error("composite coordinate types are invalid.")
    }
    for (i in seq_along(composite_ids)) {
      members <- result$composite_coordinates$primitive_members[[i]]
      expected_members <- primitive_ids[primitive_ids %in% members]
      if (!is.character(members) || length(members) < 2L || anyNA(members) ||
          anyDuplicated(members) || !identical(members, expected_members) ||
          !identical(
            as.integer(result$composite_coordinates$member_count[[i]]),
            as.integer(length(members))
          ) ||
          !identical(
            as.character(result$composite_coordinates$member_text[[i]]),
            paste(members, collapse = "|")
          ) ||
          !identical(composite_ids[[i]],
                     paste0("F[", paste(members, collapse = "|"), "]"))) {
        result_invariant_error(sprintf(
          "composite member definition is inconsistent for `%s`.",
          composite_ids[[i]]
        ))
      }
    }
  }
  numeric_axis <- c(primitive_ids, composite_ids)
  if (!identical(colnames(result$numeric_matrix), numeric_axis)) {
    result_invariant_error(
      "the numeric matrix does not match the primitive-plus-composite axis."
    )
  }
  if (any(!is.na(result$numeric_matrix) & !is.finite(result$numeric_matrix))) {
    result_invariant_error(
      "the numeric matrix contains a non-finite, non-missing value."
    )
  }

  allowed_states <- c("mapped", "NA_struct", "NA_fuse", "NA_topo")
  observed_states <- unique(as.character(result$state_matrix))
  unexpected <- setdiff(observed_states, allowed_states)
  if (anyNA(result$state_matrix) || length(unexpected)) {
    result_invariant_error(sprintf(
      "the state matrix contains missing or unknown state(s): %s.",
      paste(unexpected, collapse = ", ")
    ))
  }
  state_values <- as.vector(t(result$state_matrix))
  primitive_numeric <- as.vector(t(
    result$numeric_matrix[, primitive_ids, drop = FALSE]
  ))
  if (any(is.finite(primitive_numeric) & state_values != "mapped")) {
    result_invariant_error(
      "a non-mapped primitive cell contains finite numeric evidence."
    )
  }

  require_result_columns(
    result$state_ledger,
    c(
      "gene_id", "coordinate_id", "projected_split",
      "projected_side_a_size", "projected_side_b_size", "state",
      "reason_code", "composite_id", "numeric_available", "numeric_value",
      "numeric_status"
    ),
    "state_ledger"
  )
  expected_gene <- rep(genes, each = length(primitive_ids))
  expected_coordinate <- rep(primitive_ids, times = length(genes))
  if (!identical(as.character(result$state_ledger$gene_id), expected_gene) ||
      !identical(as.character(result$state_ledger$coordinate_id),
                 expected_coordinate)) {
    result_invariant_error(
      "the state ledger is not the complete unique gene-by-primitive axis."
    )
  }
  if (!identical(as.character(result$state_ledger$state), state_values)) {
    result_invariant_error("state ledger values disagree with `state_matrix`.")
  }
  expected_available <- is.finite(primitive_numeric)
  if (!identical(as.logical(result$state_ledger$numeric_available),
                 expected_available) ||
      !numeric_vectors_equal(result$state_ledger$numeric_value,
                             primitive_numeric)) {
    result_invariant_error(
      "state ledger numeric evidence disagrees with `numeric_matrix`."
    )
  }
  fused <- state_values == "NA_fuse"
  ledger_composite <- as.character(result$state_ledger$composite_id)
  if (any(fused & (is.na(ledger_composite) |
                   !ledger_composite %in% composite_ids)) ||
      any(!fused & !is.na(ledger_composite))) {
    result_invariant_error(
      "state ledger composite IDs disagree with NA_fuse cells."
    )
  }

  require_result_columns(
    result$composite_ledger,
    c(
      "gene_id", "composite_id", "projected_split", "recovery_status",
      "numeric_available", "numeric_value", "numeric_status"
    ),
    "composite_ledger"
  )
  composite_ledger <- result$composite_ledger
  composite_keys <- paste(
    composite_ledger$gene_id, composite_ledger$composite_id, sep = "\r"
  )
  if (anyDuplicated(composite_keys) ||
      any(!composite_ledger$gene_id %in% genes) ||
      any(!composite_ledger$composite_id %in% composite_ids)) {
    result_invariant_error("composite ledger keys are invalid or duplicated.")
  }
  expected_composite_keys <- unique(paste(
    expected_gene[fused], ledger_composite[fused], sep = "\r"
  ))
  if (!setequal(composite_keys, expected_composite_keys)) {
    result_invariant_error(
      "composite ledger rows do not exactly cover gene-specific fusion coordinates."
    )
  }
  if (any(
    as.logical(composite_ledger$numeric_available) !=
      is.finite(composite_ledger$numeric_value)
  )) {
    result_invariant_error(
      "composite ledger numeric availability and values disagree."
    )
  }
  expected_composite_numeric <- matrix(
    NA_real_, length(genes), length(composite_ids),
    dimnames = list(genes, composite_ids)
  )
  if (nrow(composite_ledger)) {
    available <- as.logical(composite_ledger$numeric_available)
    if (any(available)) {
      expected_composite_numeric[cbind(
        match(composite_ledger$gene_id[available], genes),
        match(composite_ledger$composite_id[available], composite_ids)
      )] <- composite_ledger$numeric_value[available]
    }
  }
  if (!numeric_vectors_equal(
    expected_composite_numeric,
    result$numeric_matrix[, composite_ids, drop = FALSE]
  )) {
    result_invariant_error(
      "composite ledger numeric evidence disagrees with `numeric_matrix`."
    )
  }

  require_result_columns(
    result$gene_provenance,
    c(
      "gene_id", "retained_taxon_count", "retained_taxa_key",
      "retained_taxa"
    ),
    "gene_provenance"
  )
  if (!identical(as.character(result$gene_provenance$gene_id), genes)) {
    result_invariant_error("gene provenance does not match the gene axis.")
  }
  for (i in seq_along(genes)) {
    taxa <- result$gene_provenance$retained_taxa[[i]]
    if (!is.character(taxa) || length(taxa) < 2L || anyNA(taxa) ||
        any(!nzchar(taxa)) || anyDuplicated(taxa) ||
        !identical(taxa, sort(taxa, method = "radix")) ||
        !identical(
          as.integer(result$gene_provenance$retained_taxon_count[[i]]),
          as.integer(length(taxa))
        ) ||
        !identical(
          as.character(result$gene_provenance$retained_taxa_key[[i]]),
          retained_taxa_key(taxa)
        )) {
      result_invariant_error(sprintf(
        "retained-taxon provenance is inconsistent for gene `%s`.", genes[[i]]
      ))
    }
  }

  expected_coordinate_table <- build_coordinate_table(result)
  if (!identical(result$coordinate_table, expected_coordinate_table)) {
    result_invariant_error(
      "coordinate table disagrees with primitive/composite definitions."
    )
  }
  if (!is.list(result$species_tree) ||
      !identical(result$species_tree$coordinates,
                 result$primitive_coordinates)) {
    result_invariant_error(
      "species-tree provenance disagrees with primitive coordinates."
    )
  }
  if (!is.list(result$input) ||
      !identical(as.character(result$input$gene_ids), genes)) {
    result_invariant_error("input provenance does not match the gene axis.")
  }
  require_result_columns(
    result$diagnostics,
    c("gene_id", "code", "severity", "count", "message"),
    "diagnostics"
  )
  if (any(!result$diagnostics$gene_id %in% genes) ||
      anyNA(result$diagnostics$count) || any(result$diagnostics$count < 0)) {
    result_invariant_error("diagnostic rows contain invalid genes or counts.")
  }

  expected_metadata <- list(
    gene_count = length(genes),
    primitive_coordinate_count = length(primitive_ids),
    composite_coordinate_count = length(composite_ids),
    state_schema = "single-tree-state-v1",
    numeric_policy = "finite-double-v1",
    split_key_schema = "SplitAligner-canonical-split-key-v2",
    retained_taxa_key_schema = "length-prefixed-UTF8-bytes-RT1",
    production_core = "C++17 graph-first mapper"
  )
  for (field in names(expected_metadata)) {
    if (!identical(result$metadata[[field]], expected_metadata[[field]])) {
      result_invariant_error(sprintf(
        "metadata field `%s` is inconsistent.", field
      ))
    }
  }
  if (!identical(result$metadata$mode, "fixed") &&
      !identical(result$metadata$mode, "free")) {
    result_invariant_error("metadata mode must be `fixed` or `free`.")
  }
  expected_conventions <- list(
    branch_identity = "canonical_unrooted_split",
    root_treatment = "representation_only",
    degree2_policy = "suppress_by_projected_edge_grouping",
    multifurcation_policy = "retain_actual_edges_only",
    terminal_policy = "retained_terminal_split_never_NA_topo",
    state_numeric_independence = TRUE,
    numeric_policy = "finite-double-v1",
    ordering = "deterministic_B_then_member_order",
    retained_taxa_key_schema = "length-prefixed-UTF8-bytes-RT1"
  )
  if (!identical(result$conventions, expected_conventions)) {
    result_invariant_error("core conventions are incomplete or inconsistent.")
  }

  if (isTRUE(check_version)) {
    supported <- splitaligner_core_info()
    if (!identical(result$metadata$core_version, supported$core_version) ||
        !identical(result$metadata$schema_version,
                   supported$schema_version)) {
      stop(
        sprintf(
          paste0(
            "Result core/schema `%s`/`%s` is incompatible with this package ",
            "(`%s`/`%s`)."
          ),
          result$metadata$core_version, result$metadata$schema_version,
          supported$core_version, supported$schema_version
        ),
        call. = FALSE
      )
    }
  }
  invisible(result)
}

#' Query coordinate member-set provenance
#'
#' Return the deterministic primitive-member definition of one or more result
#' coordinates. Primitive rows contain themselves as their one member;
#' composite rows expose the complete frozen primitive member set.
#'
#' @param result A `splitaligner_result` returned by [align_branches()].
#' @param coordinate_id Optional character vector of exact coordinate IDs. The
#'   default returns all primitive and composite coordinates in result order.
#' @return A data frame with coordinate type, reference split where applicable,
#'   member count/text, representation aliases, and a list-column containing
#'   exact primitive members.
#' @examples
#' species <- "((A:1,B:1):1,(C:1,D:1):1);"
#' result <- align_branches(species, "(A:1,B:2);")
#' coordinate_provenance(result, "F[B1|B2]")
#' @export
coordinate_provenance <- function(result, coordinate_id = NULL) {
  validate_splitaligner_result_object(result)
  table <- result$coordinate_table
  if (is.null(coordinate_id)) {
    return(table)
  }
  if (!is.character(coordinate_id) || anyNA(coordinate_id) ||
      any(!nzchar(coordinate_id))) {
    stop("`coordinate_id` must contain nonempty, non-missing strings.",
         call. = FALSE)
  }
  unknown <- setdiff(coordinate_id, table$coordinate_id)
  if (length(unknown)) {
    stop(
      sprintf("Unknown coordinate ID(s): %s.", paste(unknown, collapse = ", ")),
      call. = FALSE
    )
  }
  out <- table[match(coordinate_id, table$coordinate_id), , drop = FALSE]
  rownames(out) <- NULL
  out
}

#' Save a SplitAlignerR result
#'
#' Save the complete layered result as one RDS file. The stored object retains
#' coordinate definitions, ledgers, diagnostics, conventions, and core/schema
#' identifiers required for checked reload.
#'
#' @param result A `splitaligner_result` returned by [align_branches()].
#' @param file Output RDS path.
#' @param compress Compression passed to [saveRDS()].
#' @param overwrite Logical; overwrite an existing file only when explicitly
#'   `TRUE`.
#' @return Invisibly, the normalized saved path.
#' @examples
#' species <- "((A,B),(C,D));"
#' result <- align_branches(species, "((A:1,B:1),(C:1,D:1));")
#' path <- tempfile(fileext = ".rds")
#' save_splitaligner_result(result, path)
#' restored <- read_splitaligner_result(path)
#' identical(result, restored)
#' @export
save_splitaligner_result <- function(result, file, compress = TRUE,
                                     overwrite = FALSE) {
  validate_splitaligner_result_object(result)
  if (!is.character(file) || length(file) != 1L || is.na(file) ||
      !nzchar(file)) {
    stop("`file` must be one nonempty path.", call. = FALSE)
  }
  if (file.exists(file) && !isTRUE(overwrite)) {
    stop("Output file already exists; set `overwrite = TRUE` explicitly.",
         call. = FALSE)
  }
  parent <- dirname(file)
  if (!dir.exists(parent)) {
    stop("Output directory does not exist.", call. = FALSE)
  }
  saveRDS(result, file = file, compress = compress, version = 3L)
  invisible(normalizePath(file, winslash = "/", mustWork = TRUE))
}

#' Read a SplitAlignerR result
#'
#' Reload a result saved by [save_splitaligner_result()] and reject incomplete,
#' corrupted-at-the-object-level, or incompatible core/schema objects.
#'
#' @param file Existing RDS path.
#' @param check_version Logical; require the stored core and schema versions to
#'   match the currently loaded package.
#' @return A validated `splitaligner_result`.
#' @examples
#' species <- "((A,B),(C,D));"
#' result <- align_branches(species, "((A:1,B:1),(C:1,D:1));")
#' path <- tempfile(fileext = ".rds")
#' save_splitaligner_result(result, path)
#' read_splitaligner_result(path)
#' @export
read_splitaligner_result <- function(file, check_version = TRUE) {
  if (!is.character(file) || length(file) != 1L || is.na(file) ||
      !file.exists(file) || dir.exists(file)) {
    stop("`file` must identify one existing RDS file.", call. = FALSE)
  }
  result <- readRDS(file)
  validate_splitaligner_result_object(
    result, check_version = check_version
  )
  result
}

#' @export
print.splitaligner_result <- function(x, ...) {
  validate_splitaligner_result_object(x)
  counts <- table(
    factor(as.character(x$state_matrix),
           levels = c("mapped", "NA_struct", "NA_fuse", "NA_topo"))
  )
  cat(
    sprintf(
      paste0(
        "<splitaligner_result> %d genes x %d primitive coordinates; ",
        "%d composite coordinates\n"
      ),
      nrow(x$state_matrix), ncol(x$state_matrix),
      nrow(x$composite_coordinates)
    ),
    sprintf(
      "  mapped=%d  NA_struct=%d  NA_fuse=%d  NA_topo=%d\n",
      counts[["mapped"]], counts[["NA_struct"]],
      counts[["NA_fuse"]], counts[["NA_topo"]]
    ),
    sprintf(
      "  core=%s  schema=%s  mode=%s\n",
      x$metadata$core_version, x$metadata$schema_version, x$metadata$mode
    ),
    sep = ""
  )
  invisible(x)
}

#' Summarize a SplitAlignerR result
#'
#' @param object A `splitaligner_result`.
#' @param ... Reserved.
#' @return A `summary.splitaligner_result` list with overall state counts,
#'   per-gene state counts, finite numeric-evidence counts, active diagnostics,
#'   and metadata.
#' @export
summary.splitaligner_result <- function(object, ...) {
  validate_splitaligner_result_object(object)
  dots <- list(...)
  if (length(dots)) {
    stop("Additional summary arguments are not accepted.", call. = FALSE)
  }
  state_levels <- c("mapped", "NA_struct", "NA_fuse", "NA_topo")
  state_counts <- as.data.frame(
    table(factor(as.character(object$state_matrix), levels = state_levels)),
    stringsAsFactors = FALSE
  )
  names(state_counts) <- c("state", "count")

  per_gene <- t(vapply(seq_len(nrow(object$state_matrix)), function(i) {
    as.integer(table(factor(object$state_matrix[i, ], levels = state_levels)))
  }, integer(length(state_levels))))
  colnames(per_gene) <- state_levels
  per_gene <- data.frame(
    gene_id = rownames(object$state_matrix),
    per_gene,
    finite_numeric_values = rowSums(!is.na(object$numeric_matrix)),
    check.names = FALSE,
    stringsAsFactors = FALSE
  )

  out <- list(
    dimensions = c(
      genes = nrow(object$state_matrix),
      primitive_coordinates = ncol(object$state_matrix),
      composite_coordinates = nrow(object$composite_coordinates)
    ),
    state_counts = state_counts,
    gene_summary = per_gene,
    finite_numeric_values = sum(!is.na(object$numeric_matrix)),
    active_diagnostics = object$diagnostics[
      object$diagnostics$count > 0L, , drop = FALSE
    ],
    metadata = object$metadata,
    conventions = object$conventions
  )
  class(out) <- c("summary.splitaligner_result", "list")
  out
}

#' @export
print.summary.splitaligner_result <- function(x, ...) {
  cat(
    sprintf(
      "SplitAlignerR summary: %d genes, %d primitive, %d composite coordinates\n",
      x$dimensions[["genes"]], x$dimensions[["primitive_coordinates"]],
      x$dimensions[["composite_coordinates"]]
    )
  )
  print(x$state_counts, row.names = FALSE)
  cat(sprintf("Finite numeric values: %d\n", x$finite_numeric_values))
  if (nrow(x$active_diagnostics)) {
    cat(sprintf("Active diagnostic rows: %d\n", nrow(x$active_diagnostics)))
  }
  invisible(x)
}
