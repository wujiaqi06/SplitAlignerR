# Panel axes and shard ranges are small enough to index before reading any cells.
panel_manifest <- function(path) {
  if (!is.character(path) || length(path) != 1L || is.na(path) || !dir.exists(path)) {
    stop("Supply the path to a completed panel directory.", call. = FALSE)
  }
  file <- file.path(path, "manifest.rds")
  if (!file.exists(file)) stop("Panel manifest is missing.", call. = FALSE)
  m <- readRDS(file)
  if (!is.list(m) || !identical(m$format, "SplitAlignerR-panel-v1") &&
      !identical(m$format, "SplitAlignerR-panel-v2") ||
      length(m$mode) != 1L || !m$mode %in% c("free", "fixed", "paired")) {
    stop("Unrecognized panel manifest.", call. = FALSE)
  }
  if (identical(m$format, "SplitAlignerR-panel-v1")) {
    m$fusion_view <- "direct"
  } else if (!identical(m$fusion_view, "direct") && !identical(m$fusion_view, "whole")) {
    stop("Panel manifest has an invalid fusion view.", call. = FALSE)
  }
  valid_axis <- function(x) {
    is.character(x) && length(x) > 0L && !anyNA(x) &&
      all(nzchar(x)) && !anyDuplicated(x)
  }
  patterns <- m$patterns
  if (!is.data.frame(patterns) ||
      !all(c("coordinate_id", "primitive_members") %in% names(patterns)) ||
      !is.character(patterns$coordinate_id) || anyNA(patterns$coordinate_id) ||
      any(!nzchar(patterns$coordinate_id)) || anyDuplicated(patterns$coordinate_id) ||
      !is.list(patterns$primitive_members)) {
    stop("Invalid panel fusion catalog.", call. = FALSE)
  }
  s <- m$shards
  if (!valid_axis(m$genes) || !valid_axis(m$branches) ||
      !valid_axis(m$components) || !is.data.frame(s) || !nrow(s) ||
      !all(c("file", "first", "last", "sha256") %in% names(s)) ||
      !is.character(s$sha256) || anyNA(s$sha256) ||
      any(!grepl("^[a-f0-9]{64}$", s$sha256)) ||
      !valid_axis(s$file) || any(!grepl("^batch-[0-9]+\\.rds$", s$file))) {
    stop("Invalid panel axes or shard index.", call. = FALSE)
  }
  if (!is.numeric(s$first) || !is.numeric(s$last) ||
      anyNA(s$first) || anyNA(s$last) ||
      any(s$last != floor(s$last)) || any(s$last < s$first) ||
      !all(s$first == c(1, s$last[-nrow(s)] + 1)) ||
      s$last[nrow(s)] != length(m$genes)) {
    stop("Invalid panel shard ranges.", call. = FALSE)
  }
  m
}

panel_load_shard <- function(path, m, k) {
  file <- file.path(path, m$shards$file[k])
  actual <- digest::digest(file = file, algo = "sha256")
  if (!identical(actual, unname(m$shards$sha256[k]))) {
    stop(sprintf("SHA-256 mismatch for panel shard %s.", m$shards$file[k]), call. = FALSE)
  }
  readRDS(file)
}

panel_indices <- function(selection, axis, label) {
  if (!is.object(selection) && is.null(dim(selection)) && length(selection)) {
    if (is.character(selection)) {
      i <- match(selection, axis)
      if (!anyNA(i)) return(i)
    } else if (is.numeric(selection) && all(is.finite(selection)) &&
               all(selection == floor(selection) & selection >= 1 & selection <= length(axis))) {
      return(as.integer(selection))
    }
  }
  stop(sprintf("Select at least one known %s name or positive index.", label),
       call. = FALSE)
}

# Work on each selected shard once, even for repeated or out-of-order genes.
panel_row_batches <- function(m, rows) {
  split(seq_along(rows), findInterval(rows, m$shards$first))
}

panel_check_cells <- function(nrow, ncol) {
  limit <- getOption("SplitAlignerR.max_panel_cells", 1e7)
  if (!is.numeric(limit) || length(limit) != 1L || is.na(limit) || limit <= 0) {
    stop("Option SplitAlignerR.max_panel_cells must be one positive number or Inf.",
         call. = FALSE)
  }
  if (as.double(nrow) * as.double(ncol) > limit) {
    stop("Select fewer genes or columns, or explicitly raise SplitAlignerR.max_panel_cells.",
         call. = FALSE)
  }
  invisible(TRUE)
}

#' Read a slice of a disk panel
#'
#' @param path Completed directory produced by `align_panel_to_disk()`.
#' @param component Stored matrix name. Free and fixed alignments have
#'   `free_state` and `free_length`, or `fixed_state` and `fixed_length`.
#'   Paired runs also contain `paired_free` and `paired_fixed`.
#' @param genes Nonempty vector of gene IDs or positive row indices.
#' @param branches Primitive branch IDs or positive column indices.
#'   The default includes all branches.
#' @return A matrix whose rows and columns follow the selections in order.
#'   Repeated selections are preserved. Memory use includes one full batch
#'   and the requested slice.
#' @export
read_panel_matrix <- function(path, component, genes, branches = NULL) {
  m <- panel_manifest(path)
  numeric_components <- c("free_length", "fixed_length")
  all_components <- c(numeric_components, "free_state", "fixed_state",
                      "paired_free", "paired_fixed")
  if (missing(component) || !is.character(component) || length(component) != 1L ||
      !component %in% all_components || !component %in% m$components) {
    stop("Choose a matrix component stored in this panel.", call. = FALSE)
  }
  if (missing(genes)) stop("Select the genes to read.", call. = FALSE)
  rows <- panel_indices(genes, m$genes, "gene")
  cols <- if (is.null(branches)) seq_along(m$branches) else {
    panel_indices(branches, m$branches, "branch")
  }
  panel_check_cells(length(rows), length(cols))
  number <- component %in% numeric_components
  out <- matrix(if (number) NA_real_ else NA_character_, length(rows), length(cols),
                dimnames = list(m$genes[rows], m$branches[cols]))
  batches <- panel_row_batches(m, rows)
  for (name in names(batches)) {
    k <- as.integer(name)
    first <- m$shards$first[k]
    last <- m$shards$last[k]
    block <- panel_load_shard(path, m, k)[[component]]
    if (!is.matrix(block) ||
        !(if (number) is.numeric(block) else is.character(block)) ||
        !identical(rownames(block), m$genes[first:last]) ||
        !identical(colnames(block), m$branches)) {
      stop("Stored matrix does not match the panel index.", call. = FALSE)
    }
    pos <- batches[[name]]
    out[pos, ] <- block[rows[pos] - first + 1L, cols, drop = FALSE]
    rm(block)
  }
  out
}

panel_shard_groups <- function(path, m, k, role) {
  key <- if (role == "free") "groups" else "fixed_groups"
  g <- panel_load_shard(path, m, k)[[key]]
  batch_ids <- m$genes[m$shards$first[k]:m$shards$last[k]]
  if (!is.data.frame(g) || !all(c("gene_id", "composite_id") %in% names(g)) ||
      !is.character(g$gene_id) || !all(g$gene_id %in% batch_ids) ||
      !is.character(g$composite_id) || anyNA(g$composite_id) ||
      anyDuplicated(g[c("gene_id", "composite_id")])) {
    stop("Stored fusion groups do not match the panel index.", call. = FALSE)
  }
  g
}

#' Read fusion groups for selected genes
#'
#' @inheritParams read_panel_matrix
#' @param role Tree set to query, either `free` or `fixed`.
#' @return Sparse fusion records in the requested gene order. A free record
#'   includes the group's free-tree classification. Genes without groups
#'   contribute zero rows.
#' @export
read_panel_groups <- function(path, genes, role = "free") {
  m <- panel_manifest(path)
  if (length(role) != 1L || !role %in% c("free", "fixed") ||
      !m$mode %in% c(role, "paired")) {
    stop("Choose a tree role present in the panel.", call. = FALSE)
  }
  if (missing(genes)) stop("Select the genes to read.", call. = FALSE)
  rows <- panel_indices(genes, m$genes, "gene")
  ids <- m$genes[rows]
  batches <- panel_row_batches(m, rows)
  pieces <- vector("list", length(batches))
  for (i in seq_along(batches)) {
    k <- as.integer(names(batches)[i])
    g <- panel_shard_groups(path, m, k, role)
    pieces[[i]] <- g[g$gene_id %in% ids[batches[[i]]], , drop = FALSE]
    rm(g)
  }
  out <- do.call(rbind, pieces)
  levels <- unique(ids)
  by_gene <- split(seq_len(nrow(out)), factor(out$gene_id, levels = levels))
  ordered <- unlist(by_gene[match(ids, levels)], use.names = FALSE)
  out <- out[ordered, , drop = FALSE]
  rownames(out) <- NULL
  out
}
