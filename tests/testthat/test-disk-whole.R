test_that("later batches introduce whole-component columns for earlier genes", {
  folder <- tempfile("panel-cross-batch-")
  dir.create(folder)
  on.exit(unlink(folder, recursive = TRUE), add = TRUE)
  species <- file.path(folder, "reference")
  input <- file.path(folder, "genes")
  ref <- "(((((A,B),C),D),E),F,(G,H));"
  trees <- c(pair = "((((A,B):8,D):7,E):9,F,(G,H));",
             complete = "(((((A,B):3,C):5,D):7,E):9,F,(G,H));",
             triple = "(((A,B):15,E):9,F,(G,H));")
  writeLines(ref, species)
  writeLines(paste0(names(trees), trees), input)
  for (view in c("whole", "direct")) {
    panel <- align_panel_to_disk(species, input, file.path(folder, view),
                                 batch_size = 1L, fusion_view = view)
    result <- align_branches(ref, trees, fusion_view = view)
    target <- "F[B9|B10|B11]"
    rows <- c("triple", "pair", "complete", "pair")
    ids <- c(target, target)
    got <- read_panel_fusions(panel, rows, ids)
    expect_identical(got, result$numeric_matrix[rows, ids, drop=FALSE])
    details <- read_panel_fusion_cells(panel, rows, target)
    expected <- fusion_cells(result, rows, target)
    expect_identical(details, expected)
    expect_identical(details$numeric_value, if (view == "whole") rep(15, 4) else c(15, NA, NA, NA))
    f <- tempfile(tmpdir = folder)
    export_panel_matrix(panel, f, include_fusions = TRUE)
    expect_identical(utils::read.delim(f, check.names = FALSE, colClasses=c("gene_id"="character"))[[target]],
                     as.integer(result$numeric_matrix[, target]))
  }
})
