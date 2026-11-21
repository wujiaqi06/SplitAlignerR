test_that("paired panel support pools gene counts across unequal-sized shards", {
  dir <- tempfile()
  dir.create(dir)
  on.exit(unlink(dir, recursive = TRUE), add = TRUE)
  ref <- "(((A:1,B:2)91:3,C:4)84:5,((D:6,E:7)99:8,(F:9,G:10)88:11)77:12);"
  fixed <- rep("(((A,B),C),((D,E),F));", 3L)
  free <- c("(((A,C),B),((D,E),F));", "((A,C),D,((B,F),E));",
            "(((A,C),B),((D,E),F));")
  ids <- paste0("g", seq_along(free))
  ref_file <- file.path(dir, "reference.nwk")
  free_file <- file.path(dir, "free.trees")
  fixed_file <- file.path(dir, "fixed.trees")
  writeLines(ref, ref_file)
  writeLines(paste0(ids, free), free_file)
  writeLines(paste0(ids, fixed), fixed_file)
  panel <- align_panel_to_disk(ref_file, free_file, file.path(dir, "panel"),
                               mode = "paired", fixed_file = fixed_file, batch_size = 2L)
  index <- readRDS(file.path(panel, "manifest.rds"))
  expect_identical(names(index$support), c("free", "fixed"))
  expect_equal(index$shards$last, c(2L, 3L))
  for (role in c("free", "fixed")) {
    trees <- if (role == "free") free else fixed
    expected <- align_branches(ref, trees, mode = role, gene_ids = ids)
    files <- write_branch_support(expected, file.path(dir, paste0("memory-", role)))
    ledger <- index$support[[role]]
    expect_identical(ledger$file, file.path(role, c("support.tsv", "support.nwk")))
    actual <- file.path(panel, ledger$file)
    hash_file <- function(path) digest::digest(file = path, algo = "sha256")
    expect_identical(unname(vapply(actual, hash_file, character(1))), ledger$sha256)
    expect_identical(unname(vapply(files, hash_file, character(1))), ledger$sha256)
    tsv <- utils::read.delim(actual[[1L]])
    inner <- tsv[tsv$branch_type == "internal", ]
    expect_true(any(inner$n_dec == 0 & is.na(inner$support_percent)))
    if (role == "free") {
      expect_true(any(inner$n_dec == 3 & inner$n_rec == 2 &
                        abs(inner$support_percent - 200 / 3) < 1e-12, na.rm = TRUE))
      expect_true(any(inner$n_dec > 0 & inner$support_percent == 0, na.rm = TRUE))
    } else {
      expect_true(all(inner$support_percent[inner$n_dec > 0] == 100))
    }
  }
})
