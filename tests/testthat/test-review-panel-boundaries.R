review_panel_fixture <- function(root, patterns = "F[B1|B2]") {
  dir.create(root)
  genes <- c("g1", "g2")
  branches <- c("B1", "B2", "B3")
  batch <- "batch-00000001.rds"
  shard <- list(free_length = matrix(seq_len(6L), 2L, 3L,
                                    dimnames = list(genes, branches)))
  saveRDS(shard, file.path(root, batch))
  manifest <- list(
    format = "SplitAlignerR-panel-v2", mode = "free", fusion_view = "whole",
    genes = genes, branches = branches, components = "free_length",
    patterns = data.frame(coordinate_id = patterns,
                          primitive_members = I(rep(list(branches[1:2]), length(patterns))),
                          stringsAsFactors = FALSE),
    shards = data.frame(file = batch, first = 1L, last = 2L,
                        sha256 = digest::digest(file = file.path(root, batch), algo = "sha256"),
                        stringsAsFactors = FALSE)
  )
  saveRDS(manifest, file.path(root, "manifest.rds"))
  invisible(root)
}

test_that("empty fusion matrix axes retain type and the selected opposite axis", {
  panel <- review_panel_fixture(tempfile("empty-fusions-"))
  on.exit(unlink(panel, recursive = TRUE), add = TRUE)
  # Empty requests must not load batch evidence, even for repeated selections.
  unlink(file.path(panel, "batch-00000001.rds"))
  for (empty in list(character(), integer(), numeric())) {
    for (field in c("numeric_value", "recovery_status")) {
      value <- if (field == "numeric_value") NA_real_ else NA_character_
      expect_identical(read_panel_fusions(panel, c("g2", "g1", "g2"), empty, field = field),
                       matrix(value, 3L, 0L, dimnames = list(c("g2", "g1", "g2"), NULL)))
      expect_identical(read_panel_fusions(panel, empty, c(1L, 1L), field = field),
                       matrix(value, 0L, 2L, dimnames = list(NULL, rep("F[B1|B2]", 2L))))
      expect_identical(read_panel_fusions(panel, empty, empty, field = field),
                       matrix(value, 0L, 0L, dimnames = list(NULL, NULL)))
    }
  }
  for (invalid in list(NULL, logical(), NA_integer_, 0L, -1L, 1.5, Inf,
                       "unknown", factor(character()), matrix(numeric(), 0L, 0L))) {
    expect_error(read_panel_fusions(panel, invalid, character()), "gene")
    expect_error(read_panel_fusions(panel, character(), invalid), "pattern")
  }
  no_fusion <- review_panel_fixture(tempfile("no-fusions-"), character())
  on.exit(unlink(no_fusion, recursive = TRUE), add = TRUE)
  expect_identical(read_panel_fusions(no_fusion, "g1", character()),
                   matrix(NA_real_, 1L, 0L, dimnames = list("g1", NULL)))
})

test_that("export rejects dangling symlinks before reading batches without warnings", {
  skip_on_os("windows")
  root <- tempfile("export-link-")
  dir.create(root)
  on.exit(unlink(root, recursive = TRUE), add = TRUE)
  panel <- review_panel_fixture(file.path(root, "panel"))
  target <- file.path(root, "absent-target")
  output <- file.path(root, "output.tsv")
  expect_true(file.symlink(target, output))
  testthat::local_mocked_bindings(
    panel_load_shard = function(...) stop("must not read batch"), .package = "SplitAlignerR"
  )
  expect_no_warning(expect_error(export_panel_matrix(panel, output), "already occupied"))
  expect_identical(Sys.readlink(output), target)
  expect_false(file.exists(target))
  expect_false(any(grepl("^splitaligner-export-", list.files(root))))
})

test_that("export publication races preserve the competing path and its target", {
  skip_on_os("windows")
  root <- tempfile("export-race-")
  dir.create(root)
  on.exit(unlink(root, recursive = TRUE), add = TRUE)
  panel <- review_panel_fixture(file.path(root, "panel"))
  real_loader <- SplitAlignerR:::panel_load_shard
  output <- file.path(root, "output.tsv")
  target <- file.path(root, "target")
  testthat::local_mocked_bindings(panel_load_shard = function(...) {
    stopifnot(file.symlink(target, output))
    real_loader(...)
  }, .package = "SplitAlignerR")
  for (existing_target in c(FALSE, TRUE)) {
    if (existing_target) writeLines("keep existing target", target)
    expect_no_warning(expect_error(export_panel_matrix(panel, output), "already occupied"))
    expect_identical(Sys.readlink(output), target)
    if (existing_target) expect_identical(readLines(target), "keep existing target")
    else expect_false(file.exists(target))
    expect_false(any(grepl("^splitaligner-export-", list.files(root))))
    unlink(output)
  }
})

test_that("cleanup reports exact failed paths without depending on permissions", {
  failed <- file.path(tempdir(), "injected-failed[1]")
  removed <- file.path(tempdir(), "injected-removed")
  testthat::local_mocked_bindings(cpp_unlink_literal = function(paths, recursive, force) {
    as.integer(paths == failed)
  }, .package = "SplitAlignerR")
  reported <- NULL
  result <- withCallingHandlers(SplitAlignerR:::.unlink_literal(c(removed, failed)),
    splitaligner_cleanup_warning = function(w) {
      reported <<- w
      invokeRestart("muffleWarning")
    })
  expect_identical(result, 1L)
  expect_s3_class(reported, "splitaligner_cleanup_warning")
  expect_identical(reported$paths, failed)
  expect_true(grepl(failed, conditionMessage(reported), fixed = TRUE))
  expect_silent(expect_identical(SplitAlignerR:::.unlink_literal(removed), 0L))
})

test_that("cleanup failure under warn=2 preserves the export error and reports residue", {
  root <- tempfile("export-cleanup-failure-")
  dir.create(root)
  on.exit(unlink(root, recursive = TRUE), add = TRUE)
  panel <- review_panel_fixture(file.path(root, "panel"))
  testthat::local_mocked_bindings(
    cpp_unlink_literal = function(...) 1L,
    panel_load_shard = function(...) stop("injected original export failure"),
    .package = "SplitAlignerR"
  )
  old <- options(warn = 2)
  on.exit(options(old), add = TRUE)
  diagnostics <- character()
  error <- withCallingHandlers(
    tryCatch(export_panel_matrix(panel, file.path(root, "output.tsv")), error = identity),
    message = function(m) {
      diagnostics <<- c(diagnostics, conditionMessage(m))
      invokeRestart("muffleMessage")
    })
  expect_s3_class(error, "error")
  expect_identical(conditionMessage(error), "injected original export failure")
  residue <- list.files(root, pattern = "^splitaligner-export-", full.names = TRUE)
  expect_length(residue, 1L)
  reported <- diagnostics
  if (.Platform$OS.type == "windows") {
    # tempfile() and list.files(full.names = TRUE) can use different mixtures
    # of native and forward separators for the same Windows path. Still
    # require the complete residue path in the diagnostic.
    residue <- chartr("\\", "/", residue)
    reported <- chartr("\\", "/", reported)
  }
  expect_true(any(grepl(residue, reported, fixed = TRUE)))
  expect_false(file.exists(file.path(root, "output.tsv")))
})

test_that("nonrecursive literal cleanup preserves directories like base unlink", {
  root <- tempfile("nonrecursive-cleanup-")
  dir.create(root)
  on.exit(unlink(root, recursive = TRUE), add = TRUE)
  for (force in c(FALSE, TRUE)) {
    empty <- file.path(root, paste0("empty-", force))
    dir.create(empty)
    expect_warning(result <- SplitAlignerR:::.unlink_literal(empty, force = force),
                    class = "splitaligner_cleanup_warning")
    expect_identical(result, 1L)
    expect_true(dir.exists(empty))
    expect_identical(SplitAlignerR:::cpp_unlink_literal(empty, FALSE, force), 1L)
  }
  if (.Platform$OS.type != "windows") {
    link <- file.path(root, "directory-link")
    expect_true(file.symlink(empty, link))
    expect_identical(SplitAlignerR:::.unlink_literal(link), 0L)
    expect_false(file.exists(link))
    expect_true(dir.exists(empty))
  }
})
