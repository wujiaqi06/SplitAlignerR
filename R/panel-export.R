#' Export a complete disk-panel matrix as a tab-separated file
#'
#' @inheritParams read_panel_matrix
#' @param file Path to a new output file in an existing directory. Publication
#'   requires a filesystem that supports hard links. Existing paths, including
#'   dangling symbolic links, are never replaced.
#' @param include_fusions Append the global fusion-pattern columns to a
#'   `free_length` or `fixed_length` export.
#' @return The path to the finished TSV, invisibly. The first column is
#'   `gene_id`. Numeric values are written with 17 significant digits and
#'   missing values as `NA`. Rows are streamed in input order.
#' @export
export_panel_matrix <- function(path, file, component = "free_length", include_fusions = FALSE) {
  m <- panel_manifest(path)
  if (!is.character(component) || length(component) != 1L || !component %in% m$components) {
    stop("Choose a matrix component stored in this panel.", call. = FALSE)
  }
  numeric_component <- component %in% c("free_length", "fixed_length")
  if (!is.logical(include_fusions) || length(include_fusions) != 1L || is.na(include_fusions) ||
      (include_fusions && !numeric_component)) {
    stop("Set include_fusions = TRUE only for a free_length or fixed_length export.", call. = FALSE)
  }
  if (!is.character(file) || length(file) != 1L || is.na(file) || !nzchar(file) ||
      !dir.exists(dirname(file))) {
    stop("Choose a new output file in an existing directory.", call. = FALSE)
  }
  occupied <- function(path) {
    if (file.exists(path)) return(TRUE)
    link <- Sys.readlink(path)
    !is.na(link) && nzchar(link)
  }
  occupied_error <- function() {
    stop(paste0("Choose a new output file: the path is already occupied: ", file), call. = FALSE)
  }
  if (occupied(file)) occupied_error()
  temporary <- tempfile("splitaligner-export-", tmpdir = dirname(file))
  con <- NULL
  on.exit({
    if (!is.null(con)) try(close(con), silent = TRUE)
    .unlink_literal(temporary)
  }, add = TRUE)
  con <- base::file(temporary, open = "wb")
  write_row <- function(values) {
    writeLines(enc2utf8(paste(values, collapse = "\t")), con, useBytes = TRUE)
  }
  patterns <- if (include_fusions) m$patterns$coordinate_id else character()
  write_row(c("gene_id", m$branches, patterns))
  for (k in seq_len(nrow(m$shards))) {
    shard <- panel_load_shard(path, m, k)
    ids <- m$genes[m$shards$first[k]:m$shards$last[k]]
    block <- shard[[component]]
    if (!is.matrix(block) || !identical(dimnames(block), list(ids, m$branches)) ||
        !(if (numeric_component) is.numeric(block) else is.character(block))) {
      stop("Stored matrix does not match the panel index.", call. = FALSE)
    }
    legacy <- identical(m$format, "SplitAlignerR-panel-v1")
    fusion_prepared <- NULL
    fusion_rows <- NULL
    if (length(patterns) && !legacy) {
      role <- if (component == "free_length") "free" else "fixed"
      fusion_prepared <- panel_prepare_fusions(shard, m, patterns, role)
      fusion_rows <- match(ids, fusion_prepared$mapping$genes)
      if (anyNA(fusion_rows)) stop("Unknown gene ID in fusion matrix request.")
    }
    if (length(patterns) && legacy) {
      key <- if (component == "free_length") "groups" else "fixed_groups"
      g <- shard[[key]]
      if (!is.data.frame(g) || !all(c("gene_id", "composite_id", "numeric_value") %in% names(g)) ||
          !is.numeric(g$numeric_value) || anyDuplicated(g[c("gene_id", "composite_id")])) {
        stop("Invalid stored fusion values.", call. = FALSE)
      }
      gene <- match(g$gene_id, ids)
      column <- match(g$composite_id, patterns)
      if (anyNA(gene) || anyNA(column)) stop("Fusion group absent from panel index.", call. = FALSE)
      by_gene <- split(seq_len(nrow(g)), factor(gene, levels = seq_along(ids)))
      values <- legacy_numeric_text(g$numeric_value)
    }
    for (i in seq_along(ids)) {
      primitive <- block[i, ]
      if (numeric_component) primitive <- legacy_numeric_text(primitive)
      extra <- rep.int("NA", length(patterns))
      if (length(patterns) && !legacy) {
        extra <- legacy_numeric_text(.fusion_numeric_row(fusion_prepared$mapping,
                                                         fusion_rows[i], m$fusion_view))
      } else if (length(patterns)) {
        ix <- by_gene[[i]]
        extra[column[ix]] <- values[ix]
      }
      write_row(c(ids[i], primitive, extra))
    }
    rm(block, shard, fusion_prepared, fusion_rows)
  }
  close(con)
  con <- NULL
  if (!suppressWarnings(file.link(temporary, file))) {
    if (occupied(file)) occupied_error()
    stop("Could not publish the export. Choose a new path on a filesystem supporting hard links.",
         call. = FALSE)
  }
  invisible(normalizePath(file, mustWork = TRUE))
}
