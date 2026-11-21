# A pattern is defined by reference branch membership. Its projected split and
# its recovery belong to an individual gene, so they stay in the batch file.
panel_finish_patterns <- function(pattern_batches, branches) {
  entries <- unlist(pattern_batches, recursive = FALSE, use.names = FALSE)
  entries <- Filter(function(x) is.data.frame(x) && nrow(x) > 0L, entries)
  if (!length(entries)) {
    return(data.frame(coordinate_id = character(), primitive_members = I(list()),
                      stringsAsFactors = FALSE))
  }
  catalog <- do.call(rbind, entries)
  ids <- catalog$coordinate_id
  members <- catalog$primitive_members
  unique_row <- !duplicated(ids)
  first <- match(ids, ids)
  if (!all(vapply(seq_along(ids), function(i) {
    identical(members[[i]], members[[first[i]]])
  }, logical(1)))) {
    stop("The same fusion pattern has different reference members.", call. = FALSE)
  }
  if (!all(vapply(members[unique_row], function(x) {
    length(x) >= 2L && !anyDuplicated(x) && all(x %in% branches)
  }, logical(1)))) stop("Invalid reference members in the fusion catalog.", call. = FALSE)
  catalog <- catalog[unique_row, c("coordinate_id", "primitive_members"), drop = FALSE]
  catalog <- catalog[order(catalog$coordinate_id, method = "radix"), , drop = FALSE]
  rownames(catalog) <- NULL
  catalog
}

#' Look up fusion patterns across all genes in a disk panel
#' @inheritParams read_panel_matrix
#' @return One row per distinct fusion pattern, with its composite ID and
#'   original primitive reference branch IDs. Paired panels index both roles.
#' @export
panel_fusion_patterns <- function(path) panel_manifest(path)$patterns

#' Read a gene-by-fusion-pattern matrix from a disk panel
#' @inheritParams read_panel_groups
#' @param genes Gene IDs or positive row positions, in the desired order.
#'   An empty character or numeric vector requests zero rows.
#' @param patterns Composite IDs or positions in the global pattern catalog.
#'   An empty character or numeric vector requests zero columns.
#' @param field The numeric group length, or the group's recovery status.
#' @return A matrix in selection order. Values use the panel's fusion view.
#'   The recovery-status field describes directly formed groups. For the
#'   separate recovery and numeric states of a sum use read_panel_fusion_cells().
#' @export
read_panel_fusions <- function(path, genes, patterns, role = "free",
                               field = c("numeric_value", "recovery_status")) {
  field <- match.arg(field)
  m <- panel_manifest(path)
  if (length(role) != 1L || !role %in% c("free", "fixed") ||
      !m$mode %in% c(role, "paired")) stop("Choose a tree role present in the panel.", call. = FALSE)
  if (missing(genes) || missing(patterns)) stop("Select genes and fusion patterns.", call. = FALSE)
  empty_selection <- function(x) {
    !is.object(x) && is.null(dim(x)) && (is.character(x) || is.numeric(x)) && !length(x)
  }
  rows <- if (empty_selection(genes)) integer() else panel_indices(genes, m$genes, "gene")
  cols <- if (empty_selection(patterns)) integer() else {
    panel_indices(patterns, m$patterns$coordinate_id, "pattern")
  }
  panel_check_cells(length(rows), length(cols))
  selected <- m$patterns$coordinate_id[cols]
  empty <- if (field == "numeric_value") NA_real_ else NA_character_
  out <- matrix(empty, length(rows), length(cols), dimnames = list(m$genes[rows], selected))
  if (!length(rows) || !length(cols)) return(out)
  batches <- panel_row_batches(m, rows)
  for (name in names(batches)) {
    k <- as.integer(name)
    pos <- batches[[name]]
    ids <- unique(m$genes[rows[pos]])
    patterns_once <- unique(selected)
    if (field == "numeric_value" && identical(m$format, "SplitAlignerR-panel-v2")) {
      shard <- panel_load_shard(path, m, k)
      part <- panel_construct_fusions(shard, m, ids, patterns_once, role)
      out[pos, ] <- part[m$genes[rows[pos]], selected, drop = FALSE]
      next
    }
    groups <- panel_shard_groups(path, m, k, role)
    if (!field %in% names(groups)) stop("Missing fusion evidence in the batch.", call. = FALSE)
    i <- match(groups$gene_id, ids)
    j <- match(groups$composite_id, patterns_once)
    take <- which(!is.na(i) & !is.na(j))
    if (length(take)) {
      block <- matrix(empty, length(ids), length(patterns_once))
      block[cbind(i[take], j[take])] <- groups[[field]][take]
      out[pos, ] <- block[match(m$genes[rows[pos]], ids), match(selected, patterns_once), drop = FALSE]
    }
    rm(groups)
  }
  out
}

panel_prepare_fusions <- function(shard, m, patterns, role) {
  evidence <- shard[[paste0(role, "_fibers")]]
  if (is.null(evidence)) stop("Missing current-edge evidence in panel batch.", call. = FALSE)
  defs <- stats::setNames(m$patterns$primitive_members[match(patterns, m$patterns$coordinate_id)],
                         patterns)
  list(evidence = evidence, definitions = defs, mapping = .fusion_prepare(evidence, defs))
}

panel_construct_fusions <- function(shard, m, ids, patterns, role, details = FALSE) {
  prepared <- panel_prepare_fusions(shard, m, patterns, role)
  .fusion_assemble(prepared$evidence, prepared$definitions, m$fusion_view,
                   gene_ids = ids, details = details, prepared = prepared$mapping)
}

#' Inspect the construction and source edges of selected disk-panel cells
#' @inheritParams read_panel_fusions
#' @param genes Gene IDs or positive row positions, in the desired order.
#'   An empty character or numeric vector requests zero cells.
#' @param patterns Composite IDs or positive pattern positions, in the desired
#'   order. An empty character or numeric vector requests zero cells.
#' @return A data frame identifying each cell by `gene_id` and `composite_id`.
#'   Rows follow the requested pattern order, with the requested gene order
#'   within each pattern, matching [fusion_cells()]. Repeated selections repeat
#'   their rows. If either selection is empty, the same columns and types are
#'   returned with zero rows.
#' @export
read_panel_fusion_cells <- function(path, genes, patterns, role = "free") {
  m <- panel_manifest(path)
  if (!identical(m$format, "SplitAlignerR-panel-v2")) {
    stop("Rebuild this legacy direct-only panel in a new directory to trace source edges.", call. = FALSE)
  }
  if (length(role) != 1L || !role %in% c("free", "fixed") ||
      !m$mode %in% c(role, "paired")) stop("Choose a tree role present in the panel.", call. = FALSE)
  if (missing(genes) || missing(patterns)) stop("Select genes and fusion patterns.", call. = FALSE)
  empty_selection <- function(x) {
    !is.object(x) && is.null(dim(x)) && (is.character(x) || is.numeric(x)) && !length(x)
  }
  rows <- if (empty_selection(genes)) integer() else panel_indices(genes, m$genes, "gene")
  cols <- if (empty_selection(patterns)) integer() else {
    panel_indices(patterns, m$patterns$coordinate_id, "pattern")
  }
  panel_check_cells(length(rows), length(cols))
  if (!length(rows) || !length(cols)) {
    return(data.frame(
      gene_id = character(), composite_id = character(), reference_state = character(),
      reference_reason = character(), recovery_status = character(), numeric_status = character(),
      numeric_available = logical(), numeric_value = numeric(), construction_mode = character(),
      components = I(list()), stringsAsFactors = FALSE
    ))
  }
  ids <- m$genes[rows]
  selected <- m$patterns$coordinate_id[cols]
  batches <- panel_row_batches(m, rows)
  pieces <- lapply(names(batches), function(name) {
    shard <- panel_load_shard(path, m, as.integer(name))
    panel_construct_fusions(shard, m, unique(ids[batches[[name]]]), unique(selected), role, TRUE)
  })
  cells <- do.call(rbind, pieces)
  pos <- match(paste(rep(ids, times = length(cols)), rep(selected, each = length(rows)), sep = "\r"),
               paste(cells$gene_id, cells$composite_id, sep = "\r"))
  if (anyNA(pos)) stop("A selected fusion cell is missing from the batch evidence.", call. = FALSE)
  cells <- cells[pos, , drop = FALSE]
  rownames(cells) <- NULL
  cells
}
