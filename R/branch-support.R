# Older saved results predate support output and do not retain the display tree.
.validate_branch_support <- function(result, required = FALSE) {
  table <- result[["support_table"]]
  newick <- result[["support_newick"]]
  reference <- result$input[["reference_newick"]]
  if (is.null(table) && is.null(newick) && is.null(reference)) {
    if (required) stop("Run align_branches() with the original trees to obtain branch support.", call. = FALSE)
    return(invisible(NULL))
  }
  counts <- c("n_valid_topologies", "n_struct", "n_fused", "n_dec", "n_rec", "n_not_recovered")
  columns <- c("coordinate_id", "branch_type", counts, "support_fraction", "support_percent")
  coordinates <- result$primitive_coordinates
  if (!is.data.frame(table) || !identical(names(table), columns) ||
      !identical(table$coordinate_id, coordinates$coordinate_id) ||
      !identical(table$branch_type, coordinates$branch_type)) {
    result_invariant_error("support_table must use the original reference branch axis.")
  }
  valid_count <- function(x) is.numeric(x) && all(is.finite(x) & x >= 0 & x == floor(x))
  if (!all(vapply(table[counts], valid_count, logical(1))) ||
      any(table$n_valid_topologies != nrow(result$state_matrix)) ||
      any(table$n_rec + table$n_not_recovered != table$n_dec) ||
      any(table$n_dec + table$n_struct + table$n_fused > table$n_valid_topologies)) {
    result_invariant_error("branch support counts are inconsistent.")
  }
  eligible <- table$n_dec > 0
  fraction <- percent <- rep(NA_real_, nrow(table))
  fraction[eligible] <- table$n_rec[eligible] / table$n_dec[eligible]
  percent[eligible] <- 100 * table$n_rec[eligible] / table$n_dec[eligible]
  if (!identical(table$support_fraction, fraction) || !identical(table$support_percent, percent)) {
    result_invariant_error("branch support ratios disagree with the counts.")
  }
  if (!is.character(reference) || length(reference) != 1L || is.na(reference) ||
      !identical(newick, cpp_support_newick(reference, stats::setNames(percent, table$coordinate_id)))) {
    result_invariant_error("support_newick disagrees with the reference and support_table.")
  }
  invisible(NULL)
}

.write_branch_support_files <- function(table, newick, output_dir) {
  if (!is.character(output_dir) || length(output_dir) != 1L || is.na(output_dir) ||
      !nzchar(output_dir) || !dir.create(output_dir, showWarnings = FALSE)) {
    stop("output_dir must be a new directory under an existing parent.", call. = FALSE)
  }
  complete <- FALSE
  on.exit(if (!complete) unlink(output_dir, recursive = TRUE, expand = FALSE), add = TRUE)
  paths <- c(table = file.path(output_dir, "support.tsv"), tree = file.path(output_dir, "support.nwk"))
  for (col in c("support_fraction", "support_percent")) {
    table[[col]] <- legacy_numeric_text(table[[col]])
  }
  utils::write.table(table, paths[["table"]], sep = "\t", row.names = FALSE,
                     quote = FALSE, na = "NA", fileEncoding = "UTF-8")
  writeLines(enc2utf8(newick), paths[["tree"]], useBytes = TRUE)
  complete <- TRUE
  invisible(paths)
}

#' Write the branch support table and annotated reference tree
#'
#' Export the two Support outputs already computed by [align_branches()].
#' Each row describes one original reference branch. An internal branch is
#' eligible for a gene when its projected split belongs to it alone and retains
#' at least two taxa on each side. Support is the number recovered divided by
#' the number eligible, irrespective of branch lengths. Numeric internal labels
#' in the Newick tree give percentages. A percentage of zero is printed as 0.
#' A branch with no eligible genes has an NA percentage and an empty tree label.
#' If the display root divides one internal branch, both halves show its label.
#' The table uses R's primitive `coordinate_id` labels. `n_dec` counts eligible
#' genes and `n_rec` counts recoveries. Match `coordinate_id` against the
#' result's `primitive_coordinates` to look up the taxon split.
#'
#' @param result A single fixed- or free-mode result returned by [align_branches()].
#' @param output_dir A new directory in an existing parent directory.
#' @return Invisibly, the named paths to `support.tsv` (table) and `support.nwk` (tree).
#' @examples
#' genes <- c(same = "((A,B),(C,D));", different = "((A,C),(B,D));")
#' result <- align_branches("((A,B),(C,D));", genes)
#' result$support_newick
#' destination <- tempfile()
#' paths <- write_branch_support(result, destination)
#' readLines(paths[["tree"]])
#' unlink(destination, recursive = TRUE)
#' @export
write_branch_support <- function(result, output_dir) {
  if (!inherits(result, "splitaligner_result")) {
    stop("result must come from align_branches() in fixed or free mode.", call. = FALSE)
  }
  .validate_branch_support(result, required = TRUE)
  .write_branch_support_files(result$support_table, result$support_newick, output_dir)
}
