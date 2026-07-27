legacy_numeric_text <- function(value) {
  output <- rep("NA", length(value))
  finite <- is.finite(value)
  if (any(finite)) {
    output[finite] <- trimws(formatC(
      value[finite], digits = 17L, format = "g", decimal.mark = "."
    ))
  }
  output
}

composite_evidence_vectors <- function(result, gene_id, composite_id) {
  ledger <- result$composite_ledger
  available <- rep(FALSE, length(gene_id))
  value <- rep(NA_real_, length(gene_id))
  recovery_status <- rep(NA_character_, length(gene_id))
  requested <- !is.na(composite_id) & nzchar(composite_id)
  if (!nrow(ledger) || !any(requested)) {
    return(list(
      available = available,
      value = value,
      recovery_status = recovery_status
    ))
  }
  ledger_key <- paste(ledger$gene_id, ledger$composite_id, sep = "\r")
  requested_key <- paste(gene_id[requested], composite_id[requested], sep = "\r")
  ledger_index <- match(requested_key, ledger_key)
  present <- !is.na(ledger_index)
  requested_index <- which(requested)
  if (any(present)) {
    target <- requested_index[present]
    source <- ledger_index[present]
    available[target] <- ledger$numeric_available[source]
    recovery_status[target] <- ledger$recovery_status[source]
    numeric <- available[target]
    value[target[numeric]] <- ledger$numeric_value[source[numeric]]
  }
  list(
    available = available,
    value = value,
    recovery_status = recovery_status
  )
}

composite_member_text_vectors <- function(result, composite_id) {
  definitions <- result$composite_coordinates
  output <- rep(NA_character_, length(composite_id))
  requested <- !is.na(composite_id) & nzchar(composite_id)
  if (!nrow(definitions) || !any(requested)) {
    return(output)
  }
  index <- match(composite_id[requested], definitions$coordinate_id)
  output[requested] <- definitions$member_text[index]
  output
}

format_taxon_difference <- function(taxa) {
  if (!length(taxa)) "<none>" else paste(taxa, collapse = ", ")
}

validate_paired_gene_taxa <- function(fixed, free) {
  for (i in seq_len(nrow(fixed$gene_provenance))) {
    fixed_taxa <- fixed$gene_provenance$retained_taxa[[i]]
    free_taxa <- free$gene_provenance$retained_taxa[[i]]
    if (!identical(fixed_taxa, free_taxa)) {
      stop(
        sprintf(
          paste0(
            "Retained taxa differ for gene `%s`: fixed-only={%s}; ",
            "free-only={%s}."
          ),
          fixed$gene_provenance$gene_id[[i]],
          format_taxon_difference(setdiff(fixed_taxa, free_taxa)),
          format_taxon_difference(setdiff(free_taxa, fixed_taxa))
        ),
        call. = FALSE
      )
    }
  }
  invisible(TRUE)
}

validate_paired_fiber_invariance <- function(fixed, free) {
  fixed_state <- as.vector(t(fixed$state_matrix))
  free_state <- as.vector(t(free$state_matrix))
  genes <- rep(
    rownames(fixed$state_matrix), each = ncol(fixed$state_matrix)
  )
  coordinates <- rep(
    colnames(fixed$state_matrix), times = nrow(fixed$state_matrix)
  )
  invalid <- (fixed_state == "NA_fuse") != (free_state == "NA_fuse") |
    (fixed_state == "NA_struct") != (free_state == "NA_struct")
  if (any(invalid)) {
    i <- which(invalid)[[1L]]
    stop(
      sprintf(
        paste0(
          "Fiber invariance failed for gene `%s`, coordinate `%s`: ",
          "fixed state `%s`, free state `%s`."
        ),
        genes[[i]], coordinates[[i]], fixed_state[[i]], free_state[[i]]
      ),
      call. = FALSE
    )
  }
  invisible(TRUE)
}

validate_paired_axes <- function(fixed, free) {
  validate_splitaligner_result_object(fixed)
  validate_splitaligner_result_object(free)
  if (!identical(fixed$metadata$mode, "fixed")) {
    stop("`fixed` must come from `align_branches(..., mode = \"fixed\")`.",
         call. = FALSE)
  }
  if (!identical(free$metadata$mode, "free")) {
    stop("`free` must come from `align_branches(..., mode = \"free\")`.",
         call. = FALSE)
  }
  if (!identical(rownames(fixed$state_matrix), rownames(free$state_matrix))) {
    stop("Fixed and free results must have the same ordered gene axis.",
         call. = FALSE)
  }
  if (!identical(colnames(fixed$state_matrix), colnames(free$state_matrix)) ||
      !identical(fixed$primitive_coordinates$canonical_split,
                 free$primitive_coordinates$canonical_split)) {
    stop("Fixed and free results must have the same ordered coordinate axis.",
         call. = FALSE)
  }
  validate_paired_gene_taxa(fixed, free)
  validate_paired_fiber_invariance(fixed, free)
  if (!identical(fixed$metadata$core_version, free$metadata$core_version) ||
      !identical(fixed$metadata$schema_version,
                 free$metadata$schema_version) ||
      !identical(fixed$conventions, free$conventions)) {
    stop("Fixed and free results use incompatible core/schema conventions.",
         call. = FALSE)
  }
  invisible(TRUE)
}

recycle_paired_finalize_inputs <- function(...) {
  values <- list(...)
  sizes <- vapply(values, length, integer(1))
  size <- max(sizes)
  if (size == 0L) {
    return(values)
  }
  invalid <- sizes != 1L & sizes != size
  if (any(invalid)) {
    stop("Paired-finalize inputs must have length 1 or a common length.",
         call. = FALSE)
  }
  lapply(values, rep_len, length.out = size)
}

validate_paired_graph_state <- function(state, argument) {
  if (!is.character(state)) {
    stop(sprintf("`%s` must be character.", argument), call. = FALSE)
  }
  if (anyNA(state)) {
    stop(
      sprintf("Actual R missing values are invalid in `%s`.", argument),
      call. = FALSE
    )
  }
  if (any(!nzchar(state)) || any(state != trimws(state))) {
    stop(
      sprintf("`%s` graph-state tokens must be nonempty and unpadded.",
              argument),
      call. = FALSE
    )
  }
  allowed <- c("mapped", "NA_struct", "NA_fuse", "NA_topo")
  invalid <- !state %in% allowed
  if (any(invalid)) {
    bad <- unique(state[invalid])
    stop(
      sprintf(
        "Unknown `%s` graph-state token(s): %s; input-quality error.",
        argument, paste(sprintf("`%s`", bad), collapse = ", ")
      ),
      call. = FALSE
    )
  }
  state
}

validate_paired_numeric_evidence <- function(value, argument) {
  if (!is.numeric(value)) {
    stop(sprintf("`%s` must be numeric.", argument), call. = FALSE)
  }
  invalid <- !is.na(value) & !is.finite(value)
  if (any(invalid)) {
    stop(
      sprintf(
        paste0(
          "`%s` must contain only finite values or R missing values; ",
          "raw failure markers must be normalized before paired finalization."
        ),
        argument
      ),
      call. = FALSE
    )
  }
  value
}

summary_class_from_final_token <- function(token) {
  output <- token
  output[token == "NA"] <- "residual_NA"
  state <- token %in% c("NA", "NA_struct", "NA_fuse", "NA_topo")
  output[!state] <- "numeric"
  output
}

finalize_paired_cells <- function(fixed_state,
                                  fixed_primitive_numeric,
                                  fixed_fused_numeric,
                                  free_state,
                                  free_primitive_numeric,
                                  free_fused_numeric) {
  recycled <- recycle_paired_finalize_inputs(
    fixed_state,
    fixed_primitive_numeric,
    fixed_fused_numeric,
    free_state,
    free_primitive_numeric,
    free_fused_numeric
  )
  fixed_state <- validate_paired_graph_state(recycled[[1L]], "fixed_state")
  fixed_primitive_numeric <- validate_paired_numeric_evidence(
    recycled[[2L]], "fixed_primitive_numeric"
  )
  fixed_fused_numeric <- validate_paired_numeric_evidence(
    recycled[[3L]], "fixed_fused_numeric"
  )
  free_state <- validate_paired_graph_state(recycled[[4L]], "free_state")
  free_primitive_numeric <- validate_paired_numeric_evidence(
    recycled[[5L]], "free_primitive_numeric"
  )
  free_fused_numeric <- validate_paired_numeric_evidence(
    recycled[[6L]], "free_fused_numeric"
  )

  fixed_primitive_available <- is.finite(fixed_primitive_numeric)
  fixed_fused_available <- is.finite(fixed_fused_numeric)
  free_primitive_available <- is.finite(free_primitive_numeric)
  free_fused_available <- is.finite(free_fused_numeric)
  inconsistent <-
    fixed_primitive_available & fixed_state != "mapped" |
    fixed_fused_available & fixed_state != "NA_fuse" |
    free_primitive_available & free_state != "mapped" |
    free_fused_available & free_state != "NA_fuse"
  if (any(inconsistent)) {
    stop(
      paste0(
        "Paired graph states and numeric-evidence layers are inconsistent; ",
        "primitive evidence requires `mapped` and fused evidence requires ",
        "`NA_fuse`."
      ),
      call. = FALSE
    )
  }

  fixed_output <- rep("NA", length(fixed_state))
  fixed_mapped <- fixed_state == "mapped" & fixed_primitive_available
  fixed_output[fixed_mapped] <- legacy_numeric_text(
    fixed_primitive_numeric[fixed_mapped]
  )
  fixed_output[fixed_state == "NA_struct"] <- "NA_struct"
  fixed_output[fixed_state == "NA_fuse" & fixed_fused_available] <- "NA_fuse"

  free_pre <- rep("NA", length(free_state))
  free_mapped <- free_state == "mapped" & free_primitive_available
  free_pre[free_mapped] <- legacy_numeric_text(
    free_primitive_numeric[free_mapped]
  )
  free_pre[free_state == "NA_fuse" & free_fused_available] <- "NA_fuse"

  final_token <- free_pre
  final_token[free_state == "NA_struct"] <- "NA_struct"
  topo <- free_state == "NA_topo" & fixed_state == "mapped" &
    fixed_primitive_available
  final_token[topo] <- "NA_topo"

  data.frame(
    fixed_output_token = fixed_output,
    free_pre_promotion_token = free_pre,
    final_matrix_token = final_token,
    summary_class = summary_class_from_final_token(final_token),
    stringsAsFactors = FALSE,
    check.names = FALSE
  )
}

validate_finalized_token_matrix <- function(matrix) {
  if (!is.matrix(matrix) || !is.character(matrix)) {
    stop("A finalized matrix must be a character matrix.", call. = FALSE)
  }
  if (anyNA(matrix)) {
    stop("Actual R missing values are invalid in a finalized matrix.",
         call. = FALSE)
  }
  tokens <- as.vector(matrix)
  if (any(tokens != trimws(tokens)) || any(!nzchar(tokens))) {
    stop("Finalized matrix tokens must be nonempty and unpadded.",
         call. = FALSE)
  }
  state <- tokens %in% c("NA", "NA_struct", "NA_fuse", "NA_topo")
  if (any(!state)) {
    checked <- validate_branch_length_tokens(tokens[!state])
    if (any(!checked$accepted)) {
      bad <- unique(tokens[!state][!checked$accepted])
      stop(
        sprintf(
          "Finalized matrix contains invalid token(s): %s.",
          paste(sprintf("`%s`", bad), collapse = ", ")
        ),
        call. = FALSE
      )
    }
  }
  invisible(TRUE)
}

#' Apply the frozen paired finalized-matrix bookkeeping layer
#'
#' Pair fixed-topology and free-topology single-tree results without modifying
#' either graph-state ledger. The finalized matrix is computed separately from
#' graph/fiber provenance. Literal `"NA"` is an intentional finalized token;
#' `residual_NA` is only its descriptive summary name, not a graph state.
#'
#' @param fixed A `splitaligner_result` generated with `mode = "fixed"`.
#' @param free A `splitaligner_result` generated with `mode = "free"`.
#' @return A `splitaligner_paired_result` containing graph states, fixed and
#'   free pre-promotion matrices, the finalized free matrix, a per-cell ledger,
#'   literal-`NA` summary rows, conventions, and versioned metadata. The input
#'   single-tree results are not modified.
#' @details The free pre-promotion layer contains a numeric token only for a
#'   mapped primitive with finite evidence, `NA_fuse` only for a fused state
#'   with finite composite evidence, and literal `NA` otherwise. Paired
#'   finalization then promotes graph-state `NA_struct` to `NA_struct`, and
#'   promotes graph-state `NA_topo` to `NA_topo` only when the fixed primitive
#'   is mapped with finite evidence. Finite evidence on a fixed fused
#'   coordinate never satisfies that primitive gate. A literal finalized `NA`
#'   remains `NA` on serialization and is summarized as `residual_NA`.
#' @examples
#' species <- "(((A,B),C),((D,E),F));"
#' fixed <- align_branches(
#'   species, c(g = "((A:1,B:1):1,(D:1,E:1):1);"), mode = "fixed"
#' )
#' free <- align_branches(
#'   species, c(g = "((A:1,D:1):1,(B:1,E:1):1);"), mode = "free"
#' )
#' paired <- pair_alignment_results(fixed, free)
#' paired$residual_NA
#' @export
pair_alignment_results <- function(fixed, free) {
  validate_paired_axes(fixed, free)
  genes <- rownames(free$state_matrix)
  coordinates <- colnames(free$state_matrix)
  gene_count <- length(genes)
  coordinate_count <- length(coordinates)
  cell_gene <- rep(genes, each = coordinate_count)
  cell_coordinate <- rep(coordinates, times = gene_count)
  branch_type <- rep(
    fixed$primitive_coordinates$branch_type, times = gene_count
  )
  fixed_state <- as.vector(t(fixed$state_matrix))
  free_state <- as.vector(t(free$state_matrix))
  fixed_numeric <- as.vector(t(
    fixed$numeric_matrix[, coordinates, drop = FALSE]
  ))
  free_numeric <- as.vector(t(
    free$numeric_matrix[, coordinates, drop = FALSE]
  ))
  fixed_numeric_available <- is.finite(fixed_numeric)
  free_numeric_available <- is.finite(free_numeric)
  fixed_composite <- as.character(fixed$state_ledger$composite_id)
  free_composite <- as.character(free$state_ledger$composite_id)
  fixed_composite_evidence <- composite_evidence_vectors(
    fixed, cell_gene, fixed_composite
  )
  free_composite_evidence <- composite_evidence_vectors(
    free, cell_gene, free_composite
  )
  fixed_fiber_member_set <- composite_member_text_vectors(
    fixed, fixed_composite
  )
  free_fiber_member_set <- composite_member_text_vectors(
    free, free_composite
  )

  finalized <- finalize_paired_cells(
    fixed_state = fixed_state,
    fixed_primitive_numeric = fixed_numeric,
    fixed_fused_numeric = fixed_composite_evidence$value,
    free_state = free_state,
    free_primitive_numeric = free_numeric,
    free_fused_numeric = free_composite_evidence$value
  )
  fixed_final_value <- finalized$fixed_output_token
  free_pre_value <- finalized$free_pre_promotion_token
  final_value <- finalized$final_matrix_token
  summary_class <- finalized$summary_class

  fixed_final <- matrix(
    fixed_final_value, gene_count, coordinate_count, byrow = TRUE,
    dimnames = list(genes, coordinates)
  )
  free_pre <- matrix(
    free_pre_value, gene_count, coordinate_count, byrow = TRUE,
    dimnames = list(genes, coordinates)
  )
  final_matrix <- matrix(
    final_value, gene_count, coordinate_count, byrow = TRUE,
    dimnames = list(genes, coordinates)
  )
  validate_finalized_token_matrix(fixed_final)
  validate_finalized_token_matrix(final_matrix)

  paired_ledger <- data.frame(
    gene_id = cell_gene,
    coordinate_id = cell_coordinate,
    branch_type = branch_type,
    fixed_primitive_state = fixed_state,
    free_primitive_state = free_state,
    fixed_fiber_member_set = fixed_fiber_member_set,
    free_fiber_member_set = free_fiber_member_set,
    fixed_primitive_numeric_available = fixed_numeric_available,
    free_primitive_numeric_available = free_numeric_available,
    fixed_fused_numeric_available = fixed_composite_evidence$available,
    free_fused_numeric_available = free_composite_evidence$available,
    fixed_composite_coordinate = fixed_composite,
    free_composite_coordinate = free_composite,
    fixed_composite_recovery_status =
      fixed_composite_evidence$recovery_status,
    free_composite_recovery_status =
      free_composite_evidence$recovery_status,
    free_pre_promotion_token = free_pre_value,
    final_matrix_token = final_value,
    summary_class = summary_class,
    residual_NA = final_value == "NA",
    stringsAsFactors = FALSE,
    check.names = FALSE
  )
  residual_rows <- paired_ledger[paired_ledger$residual_NA, , drop = FALSE]
  fixed_fusion_event_count <- 0L
  if (nrow(residual_rows)) {
    fusion_rows <- !is.na(residual_rows$fixed_composite_coordinate)
    fixed_fusion_event_count <- length(unique(paste(
      residual_rows$gene_id[fusion_rows],
      residual_rows$fixed_composite_coordinate[fusion_rows], sep = "\r"
    )))
  }
  out <- list(
    semantic_state_matrix = free$state_matrix,
    fixed_final_matrix = fixed_final,
    free_pre_promotion_matrix = free_pre,
    final_matrix = final_matrix,
    paired_ledger = paired_ledger,
    residual_NA = residual_rows,
    coordinate_table = free$coordinate_table,
    conventions = list(
      graph_layer = "unchanged_single_tree_state_v1",
      paired_finalize_rule = "structured_sem_003_v1",
      residual_NA_is_graph_state = FALSE,
      residual_NA_is_summary_name_for_literal_NA = TRUE,
      finalized_generic_NA_is_intentional = TRUE,
      NA_topo_requires_finite_fixed_primitive_numeric_evidence = TRUE,
      fixed_fused_numeric_does_not_satisfy_primitive_gate = TRUE,
      finalized_perl_matrices_are_authoritative = TRUE,
      empirical_conflict_is_classification_predicate = FALSE
    ),
    metadata = list(
      core_version = free$metadata$core_version,
      schema_version = free$metadata$schema_version,
      paired_schema = "1.0.0",
      gene_count = gene_count,
      primitive_coordinate_count = coordinate_count,
      residual_NA_count = nrow(residual_rows),
      residual_NA_gene_count = length(unique(residual_rows$gene_id)),
      residual_NA_internal_coordinate_count = length(unique(
        residual_rows$coordinate_id[residual_rows$branch_type == "internal"]
      )),
      residual_NA_terminal_count = sum(
        residual_rows$branch_type == "terminal"
      ),
      residual_NA_fixed_fusion_event_count = fixed_fusion_event_count
    )
  )
  class(out) <- c("splitaligner_paired_result", "list")
  out
}

#' @export
print.splitaligner_paired_result <- function(x, ...) {
  cat(sprintf(
    paste0(
      "<splitaligner_paired_result> %d genes x %d coordinates; ",
      "literal_NA/residual_NA=%d\n"
    ),
    x$metadata$gene_count, x$metadata$primitive_coordinate_count,
    x$metadata$residual_NA_count
  ))
  invisible(x)
}
