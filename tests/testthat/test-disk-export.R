test_that("TSV export writes every gene against the global primitive and fusion axes", {
  folder <- tempfile("panel-export-")
  dir.create(folder)
  on.exit(unlink(folder, recursive = TRUE), add = TRUE)
  reference <- "((A,B),C,(D,(E,F)));"
  # The second gene is the first to form a fusion. Both records contain
  # lengths that lose precision if the text writer uses only 15 digits.
  trees <- c(early = "((A:1.2345678901234567,B),C,(D,(E,F)));",
             late = "((A,B):0.12345678901234566,D,(E,F));")
  reference_path <- file.path(folder, "reference.nwk")
  input <- file.path(folder, "free.nwk")
  writeLines(reference, reference_path)
  writeLines(paste0(names(trees), trees), input)
  panel <- file.path(folder, "panel")
  align_panel_to_disk(reference_path, input, panel, batch_size = 1L)
  free <- align_branches(reference, trees)
  primitive <- colnames(free$state_matrix)
  pattern <- free_fusion_groups(free)$composite_id
  expect_length(pattern, 1L)

  old <- options(digits = 3L)
  on.exit(options(old), add = TRUE)
  read_numeric_tsv <- function(file, axes) {
    utils::read.delim(file, header = TRUE, stringsAsFactors = FALSE,
                      check.names = FALSE, quote = "", na.strings = "NA",
                      colClasses = c("character", rep("numeric", length(axes))))
  }
  for (all_columns in c(FALSE, TRUE)) {
    axes <- if (all_columns) c(primitive, pattern) else primitive
    file <- file.path(folder, if (all_columns) "all.tsv" else "primitive.tsv")
    export_panel_matrix(panel, file, component = "free_length",
                        include_fusions = all_columns)
    table <- read_numeric_tsv(file, axes)
    expect_identical(names(table), c("gene_id", axes))
    expect_identical(table$gene_id, names(trees))
    observed <- as.matrix(table[, axes, drop = FALSE])
    rownames(observed) <- table$gene_id
    expect_identical(observed, free$numeric_matrix[, axes, drop = FALSE])
    if (all_columns) {
      expect_identical(observed["early", pattern], NA_real_)
      expect_identical(observed["late", pattern], 0.12345678901234566)
      # Require the explicit missing token. A blank field is not interchangeable.
      data_lines <- strsplit(readLines(file)[-1L], "\t", fixed = TRUE)
      expect_identical(tail(data_lines[[1L]], 1L), "NA")
      expect_identical(tail(data_lines[[2L]], 1L), sprintf("%.17g", 0.12345678901234566))
    }
  }

  existing <- file.path(folder, "existing.tsv")
  writeLines("my existing file", existing)
  expect_error(export_panel_matrix(panel, existing))
  expect_identical(readLines(existing), "my existing file")

  info <- readRDS(file.path(panel, "manifest.rds"))
  second <- file.path(panel, info$shards$file[2L])
  expect_true(file.rename(second, paste0(second, ".off")))
  broken <- file.path(folder, "partial.tsv")
  expect_error(suppressWarnings(export_panel_matrix(panel, broken, include_fusions = TRUE)))
  expect_false(file.exists(broken))
})
