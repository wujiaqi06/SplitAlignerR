args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 7L) {
  stop(
    paste(
      "usage: full_residual_authority.R SPECIES_TREE FIXED_TREES FREE_TREES",
      "EXPECTED_LEDGER OBSERVED_TSV REPORT_TXT CHUNK_SIZE"
    ),
    call. = FALSE
  )
}

library(SplitAlignerR)

species_tree <- normalizePath(args[[1L]], mustWork = TRUE)
fixed_path <- normalizePath(args[[2L]], mustWork = TRUE)
free_path <- normalizePath(args[[3L]], mustWork = TRUE)
ledger_path <- normalizePath(args[[4L]], mustWork = TRUE)
observed_path <- args[[5L]]
report_path <- args[[6L]]
chunk_size <- suppressWarnings(as.integer(args[[7L]]))
if (is.na(chunk_size) || chunk_size < 1L) {
  stop("CHUNK_SIZE must be a positive integer", call. = FALSE)
}

fixed_input <- SplitAlignerR:::as_gene_newicks(fixed_path)
free_input <- SplitAlignerR:::as_gene_newicks(free_path)
stopifnot(identical(fixed_input$ids, free_input$ids))
gene_count <- length(fixed_input$ids)
stopifnot(gene_count == 2275L)

expected <- utils::read.delim(
  ledger_path,
  quote = "",
  na.strings = character(0),
  stringsAsFactors = FALSE,
  check.names = FALSE
)
stopifnot(
  identical(names(expected), c("gene_id", "branch_id")),
  nrow(expected) == 407L
)
expected_keys <- paste(expected$gene_id, expected$branch_id, sep = "\r")
stopifnot(length(unique(expected_keys)) == 407L)

residual_chunks <- list()
primitive_count <- NA_integer_
start_rows <- seq.int(1L, gene_count, by = chunk_size)

for (chunk_index in seq_along(start_rows)) {
  first <- start_rows[[chunk_index]]
  last <- min(gene_count, first + chunk_size - 1L)
  index <- seq.int(first, last)
  ids <- fixed_input$ids[index]

  fixed <- align_branches(
    species_tree,
    fixed_input$newicks[index],
    mode = "fixed",
    gene_ids = ids
  )
  free <- align_branches(
    species_tree,
    free_input$newicks[index],
    mode = "free",
    gene_ids = ids
  )
  paired <- pair_alignment_results(fixed, free)

  if (is.na(primitive_count)) {
    primitive_count <- paired$metadata$primitive_coordinate_count
  }
  stopifnot(
    paired$metadata$primitive_coordinate_count == primitive_count,
    nrow(paired$semantic_state_matrix) == length(index),
    ncol(paired$semantic_state_matrix) == primitive_count
  )
  if (nrow(paired$residual_NA)) {
    residual_chunks[[length(residual_chunks) + 1L]] <- paired$residual_NA
  }
  message(
    sprintf(
      "chunk %d/%d genes %d-%d residual_so_far=%d",
      chunk_index,
      length(start_rows),
      first,
      last,
      sum(vapply(residual_chunks, nrow, integer(1)))
    )
  )
  rm(fixed, free, paired)
  invisible(gc())
}

observed <- if (length(residual_chunks)) {
  do.call(rbind, residual_chunks)
} else {
  stop("full authority produced no residual rows", call. = FALSE)
}
rownames(observed) <- NULL
observed_keys <- paste(observed$gene_id, observed$coordinate_id, sep = "\r")
event_keys <- paste(
  observed$gene_id, observed$fixed_composite_coordinate, sep = "\r"
)

checks <- c(
  genes = gene_count == 2275L,
  primitive_branches = primitive_count == 601L,
  all_matrix_cells = gene_count * primitive_count == 1367275L,
  residual_cells = nrow(observed) == 407L,
  residual_genes = length(unique(observed$gene_id)) == 189L,
  internal_branches = length(unique(
    observed$coordinate_id[observed$branch_type == "internal"]
  )) == 82L,
  fusion_events = length(unique(event_keys)) == 202L,
  terminal_residual = sum(observed$branch_type == "terminal") == 0L,
  authority_keys = setequal(observed_keys, expected_keys),
  authority_keys_unique = length(unique(observed_keys)) == 407L,
  fixed_primitive_state = all(observed$fixed_primitive_state == "NA_fuse"),
  fixed_primitive_numeric = all(
    !observed$fixed_primitive_numeric_available
  ),
  fixed_fused_numeric = all(observed$fixed_fused_numeric_available),
  free_pre_promotion = all(observed$free_pre_promotion_token == "NA"),
  final_token = all(observed$final_matrix_token == "NA"),
  summary_class = all(observed$summary_class == "residual_NA")
)

observed <- observed[order(observed$gene_id, observed$coordinate_id), ]
utils::write.table(
  observed,
  file = observed_path,
  sep = "\t",
  quote = FALSE,
  row.names = FALSE,
  na = "NA"
)
writeLines(
  c(
    sprintf("chunk_size: %d", chunk_size),
    sprintf("chunk_count: %d", length(start_rows)),
    sprintf("genes: %d", gene_count),
    sprintf("primitive_branches: %d", primitive_count),
    sprintf("all_matrix_cells: %d", gene_count * primitive_count),
    sprintf("residual_cells: %d", nrow(observed)),
    sprintf("residual_genes: %d", length(unique(observed$gene_id))),
    sprintf(
      "internal_branches: %d",
      length(unique(
        observed$coordinate_id[observed$branch_type == "internal"]
      ))
    ),
    sprintf("fusion_events: %d", length(unique(event_keys))),
    sprintf(
      "terminal_residual: %d",
      sum(observed$branch_type == "terminal")
    ),
    sprintf("checks_passed: %d/%d", sum(checks), length(checks)),
    paste(names(checks), ifelse(checks, "PASS", "FAIL"), sep = ": "),
    sprintf("overall_status: %s", if (all(checks)) "PASS" else "FAIL")
  ),
  con = report_path,
  useBytes = TRUE
)
if (!all(checks)) {
  stop(
    sprintf(
      "full residual authority failed: %s",
      paste(names(checks)[!checks], collapse = ", ")
    ),
    call. = FALSE
  )
}
