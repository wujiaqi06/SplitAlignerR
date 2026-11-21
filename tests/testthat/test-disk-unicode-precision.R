test_that("two-pass panels preserve named records and doubles across shards", {
  ref <- "(('A one',B),C,(D,(E,F)));"
  ids <- c("\u57fa\u56e0_\u03b1", "\u907a\u4f1d\u5b50_\u03b2", "\u03b3")
  trees <- c("(('A one':1.2345678901234567,B),C,(D,(E,F)));",
             "(('A one',B):0.12345678901234566,D,(E,F));",
             "(('A one',D),B,(E,F));")
  tmp <- tempfile()
  dir.create(tmp)
  on.exit(unlink(tmp, recursive = TRUE), add = TRUE)
  species <- file.path(tmp, "ref.nwk")
  genes <- file.path(tmp, "genes.nwk")
  panel <- file.path(tmp, "panel")
  writeLines(ref, species)
  writeLines(enc2utf8(paste0(ids, trees)), genes, useBytes = TRUE)
  align_panel_to_disk(species, genes, panel, mode = "free", batch_size = 1L)

  expected <- align_branches(ref, trees, mode = "free", gene_ids = setNames(ids, ids))
  manifest <- readRDS(file.path(panel, "manifest.rds"))
  expect_identical(manifest$genes, ids)
  expect_identical(nrow(manifest$shards), 3L)
  branches <- manifest$branches
  patterns <- panel_fusion_patterns(panel)$coordinate_id
  expect_length(patterns, 1L)
  expect_identical(read_panel_matrix(panel, "free_length", rev(ids), branches),
                   expected$numeric_matrix[rev(ids), branches, drop = FALSE])
  fusions <- read_panel_fusions(panel, ids, patterns)
  expect_identical(fusions, expected$numeric_matrix[ids, patterns, drop = FALSE])
  expect_identical(fusions[2, 1], 0.12345678901234566)

  file <- file.path(tmp, "lengths.tsv")
  export_panel_matrix(panel, file, include_fusions = TRUE)
  axes <- c(branches, patterns)
  tab <- utils::read.delim(file, check.names = FALSE, stringsAsFactors = FALSE,
                           fileEncoding = "UTF-8", colClasses = c("character", rep("numeric", length(axes))))
  numeric <- as.matrix(tab[, axes, drop = FALSE])
  rownames(numeric) <- tab[[1L]]
  expect_identical(numeric, expected$numeric_matrix[ids, axes, drop = FALSE])
})
