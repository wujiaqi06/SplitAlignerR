test_that("frozen 302-mammal example matches legacy cell classes", {
  example_dir <- Sys.getenv("SPLITALIGNERR_302MAMMAL_DIR", unset = "")
  skip_if(
    !nzchar(example_dir) || !dir.exists(example_dir),
    "Set SPLITALIGNERR_302MAMMAL_DIR to the frozen examples/302mammal directory"
  )

  required <- c(
    "input/speciesTree302.nwk",
    "input/fix_tree.examples.nwk",
    "input/free_tree.examples.nwk",
    "expected/final.fix.na_classified.txt",
    "expected/final.free.na_classified.txt"
  )
  missing <- required[!file.exists(file.path(example_dir, required))]
  expect_length(missing, 0L)

  species <- file.path(example_dir, "input/speciesTree302.nwk")
  fixed_input <- SplitAlignerR:::as_gene_newicks(
    file.path(example_dir, "input/fix_tree.examples.nwk")
  )
  free_input <- SplitAlignerR:::as_gene_newicks(
    file.path(example_dir, "input/free_tree.examples.nwk")
  )
  common_genes <- intersect(fixed_input$ids, free_input$ids)
  expect_identical(
    common_genes,
    c("A1BG", "A1CF", "A2M", "A4GALT", "A4GNT")
  )

  fixed <- align_branches(
    species,
    fixed_input$newicks[match(common_genes, fixed_input$ids)],
    mode = "fixed",
    gene_ids = common_genes
  )
  free <- align_branches(
    species,
    free_input$newicks[match(common_genes, free_input$ids)],
    mode = "free",
    gene_ids = common_genes
  )
  paired <- pair_alignment_results(fixed, free)

  read_expected <- function(path) {
    table <- utils::read.delim(
      path,
      check.names = FALSE,
      quote = "",
      na.strings = character(0),
      stringsAsFactors = FALSE
    )
    matrix <- as.matrix(table[-1L])
    rownames(matrix) <- table[[1L]]
    matrix
  }
  expected_fixed <- read_expected(file.path(
    example_dir, "expected/final.fix.na_classified.txt"
  ))
  expected_free <- read_expected(file.path(
    example_dir, "expected/final.free.na_classified.txt"
  ))
  observed_fixed <- paired$fixed_final_matrix[
    rownames(expected_fixed), colnames(expected_fixed), drop = FALSE
  ]
  observed_free <- paired$final_matrix[
    rownames(expected_free), colnames(expected_free), drop = FALSE
  ]

  numeric_pattern <- paste0(
    "^[+-]?(?:[0-9]+(?:[.][0-9]*)?|[.][0-9]+)",
    "(?:[eE][+-]?[0-9]+)?$"
  )
  classify <- function(matrix) {
    output <- matrix
    output[grepl(numeric_pattern, output)] <- "numeric"
    output
  }
  expect_identical(classify(observed_fixed), classify(expected_fixed))
  expect_identical(classify(observed_free), classify(expected_free))
  expect_identical(dim(observed_fixed), c(5L, 601L))
  expect_identical(dim(observed_free), c(5L, 601L))

  compare_numeric <- function(expected, observed) {
    numeric_cells <- grepl(numeric_pattern, expected)
    max(abs(
      as.numeric(expected[numeric_cells]) -
        as.numeric(observed[numeric_cells])
    ))
  }
  expect_lte(compare_numeric(expected_fixed, observed_fixed), 1e-12)
  expect_lte(compare_numeric(expected_free, observed_free), 5e-8)
  expect_identical(
    as.integer(table(factor(
      expected_free[!grepl(numeric_pattern, expected_free)],
      levels = c("NA", "NA_fuse", "NA_struct", "NA_topo")
    ))),
    c(6L, 141L, 95L, 382L)
  )
  expected_residual_index <- which(expected_free == "NA", arr.ind = TRUE)
  expected_residual_keys <- paste(
    rownames(expected_free)[expected_residual_index[, "row"]],
    colnames(expected_free)[expected_residual_index[, "col"]],
    sep = "\r"
  )
  expect_identical(length(expected_residual_keys), 6L)
  observed_residual_keys <- paste(
    paired$residual_NA$gene_id,
    paired$residual_NA$coordinate_id,
    sep = "\r"
  )
  expect_setequal(observed_residual_keys, expected_residual_keys)
  expect_true(all(paired$residual_NA$fixed_primitive_state == "NA_fuse"))
  expect_true(all(!paired$residual_NA$fixed_primitive_numeric_available))
  expect_true(all(paired$residual_NA$free_pre_promotion_token == "NA"))
  expect_true(all(paired$residual_NA$final_matrix_token == "NA"))
  expect_true(all(paired$residual_NA$summary_class == "residual_NA"))
})

test_that("full authority recovers the frozen 407 literal-NA ledger", {
  authority_dir <- Sys.getenv("SPLITALIGNERR_RESIDUAL_NA_DIR", unset = "")
  example_dir <- Sys.getenv("SPLITALIGNERR_302MAMMAL_DIR", unset = "")
  full_input_dir <- Sys.getenv("SPLITALIGNERR_2275_INPUT_DIR", unset = "")
  skip_if(
    !nzchar(authority_dir) || !dir.exists(authority_dir) ||
      !nzchar(example_dir) || !dir.exists(example_dir) ||
      !nzchar(full_input_dir) || !dir.exists(full_input_dir),
    paste0(
      "Set SPLITALIGNERR_RESIDUAL_NA_DIR, SPLITALIGNERR_302MAMMAL_DIR, ",
      "and SPLITALIGNERR_2275_INPUT_DIR to the frozen authority directories"
    )
  )
  required <- c(
    file.path(example_dir, "input/speciesTree302.nwk"),
    file.path(full_input_dir, "fix.2275genes.nwk"),
    file.path(full_input_dir, "free.2275genes.nwk"),
    file.path(authority_dir, "01_residual_NA_cell_ledger.tsv")
  )
  expect_true(all(file.exists(required)))

  fixed_input <- SplitAlignerR:::as_gene_newicks(required[[2L]])
  free_input <- SplitAlignerR:::as_gene_newicks(required[[3L]])
  expect_identical(fixed_input$ids, free_input$ids)
  fixed <- align_branches(
    required[[1L]], fixed_input$newicks,
    mode = "fixed", gene_ids = fixed_input$ids
  )
  free <- align_branches(
    required[[1L]], free_input$newicks,
    mode = "free", gene_ids = free_input$ids
  )
  paired <- pair_alignment_results(fixed, free)
  authority <- utils::read.delim(
    required[[4L]], quote = "", na.strings = character(0),
    stringsAsFactors = FALSE, check.names = FALSE
  )
  expect_identical(nrow(authority), 407L)
  expect_identical(nrow(paired$residual_NA), 407L)
  expected_keys <- paste(authority$gene_id, authority$branch_id, sep = "\r")
  observed_keys <- paste(
    paired$residual_NA$gene_id,
    paired$residual_NA$coordinate_id,
    sep = "\r"
  )
  expect_setequal(observed_keys, expected_keys)
  expect_identical(paired$metadata$residual_NA_count, 407L)
  expect_identical(paired$metadata$residual_NA_gene_count, 189L)
  expect_identical(
    paired$metadata$residual_NA_internal_coordinate_count, 82L
  )
  expect_identical(
    paired$metadata$residual_NA_fixed_fusion_event_count, 202L
  )
  expect_identical(paired$metadata$residual_NA_terminal_count, 0L)
  expect_true(all(paired$residual_NA$branch_type == "internal"))
  expect_true(all(paired$residual_NA$fixed_primitive_state == "NA_fuse"))
  expect_true(all(paired$residual_NA$free_primitive_state == "NA_fuse"))
  expect_true(all(!paired$residual_NA$fixed_primitive_numeric_available))
  expect_true(all(paired$residual_NA$fixed_fused_numeric_available))
  expect_true(all(paired$residual_NA$free_pre_promotion_token == "NA"))
  expect_true(all(paired$residual_NA$final_matrix_token == "NA"))
  expect_true(all(paired$residual_NA$summary_class == "residual_NA"))
})
