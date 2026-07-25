args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2L) {
  stop("usage: determinism.R AUTHORITY_302_DIR OUTPUT_REPORT", call. = FALSE)
}

library(SplitAlignerR)

authority_dir <- normalizePath(args[[1L]], mustWork = TRUE)
output_report <- args[[2L]]

read_inputs <- function(file) {
  SplitAlignerR:::as_gene_newicks(file)
}

sort_rows <- function(x, columns) {
  if (!nrow(x)) {
    return(x)
  }
  index <- do.call(order, unname(x[columns]))
  x <- x[index, , drop = FALSE]
  rownames(x) <- NULL
  x
}

sort_matrix_rows <- function(x) {
  x[order(rownames(x)), , drop = FALSE]
}

canonical_result <- function(x) {
  x$state_matrix <- sort_matrix_rows(x$state_matrix)
  x$numeric_matrix <- sort_matrix_rows(x$numeric_matrix)
  x$state_ledger <- sort_rows(
    x$state_ledger, c("gene_id", "coordinate_id")
  )
  x$composite_ledger <- sort_rows(
    x$composite_ledger, c("gene_id", "composite_id")
  )
  x$gene_provenance <- sort_rows(x$gene_provenance, "gene_id")
  x$diagnostics <- sort_rows(x$diagnostics, c("gene_id", "code"))
  x$input$gene_ids <- sort(x$input$gene_ids, method = "radix")
  x
}

canonical_paired <- function(x) {
  x$semantic_state_matrix <- sort_matrix_rows(x$semantic_state_matrix)
  x$fixed_final_matrix <- sort_matrix_rows(x$fixed_final_matrix)
  x$free_pre_promotion_matrix <- sort_matrix_rows(
    x$free_pre_promotion_matrix
  )
  x$final_matrix <- sort_matrix_rows(x$final_matrix)
  x$paired_ledger <- sort_rows(
    x$paired_ledger, c("gene_id", "coordinate_id")
  )
  x$residual_NA <- sort_rows(x$residual_NA, c("gene_id", "coordinate_id"))
  x
}

species <- file.path(authority_dir, "input", "speciesTree302.nwk")
fixed_input <- read_inputs(file.path(
  authority_dir, "input", "fix_tree.examples.nwk"
))
free_input <- read_inputs(file.path(
  authority_dir, "input", "free_tree.examples.nwk"
))
common_genes <- intersect(fixed_input$ids, free_input$ids)

run_once <- function(gene_order) {
  fixed <- align_branches(
    species,
    fixed_input$newicks[match(gene_order, fixed_input$ids)],
    mode = "fixed",
    gene_ids = gene_order
  )
  free <- align_branches(
    species,
    free_input$newicks[match(gene_order, free_input$ids)],
    mode = "free",
    gene_ids = gene_order
  )
  list(
    fixed = canonical_result(fixed),
    free = canonical_result(free),
    paired = canonical_paired(pair_alignment_results(fixed, free))
  )
}

runs <- replicate(3L, run_once(common_genes), simplify = FALSE)
repeat_identical <- identical(runs[[1L]], runs[[2L]]) &&
  identical(runs[[1L]], runs[[3L]])
reordered <- run_once(rev(common_genes))
order_identical <- identical(runs[[1L]], reordered)

report <- c(
  sprintf("repeat_count: %d", length(runs)),
  sprintf("same_input_canonical_output_identical: %s", repeat_identical),
  sprintf("reversed_gene_input_canonical_output_identical: %s", order_identical),
  paste0(
    "parallel_serial_comparison: NOT APPLICABLE; ",
    "V1 exposes no parallel execution parameter"
  ),
  sprintf("overall_status: %s", if (repeat_identical && order_identical) "PASS" else "FAIL")
)
writeLines(report, output_report, useBytes = TRUE)
if (!repeat_identical || !order_identical) {
  stop("determinism gate failed", call. = FALSE)
}
