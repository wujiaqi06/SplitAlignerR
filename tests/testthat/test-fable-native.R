test_that("Newick decimals keep their meaning in a comma-decimal locale", {
  # Host locale changes are process-wide. Use a fresh R process with the
  # same library paths as this test, including the R CMD check install.
  script <- test_path("fixtures", "comma-numeric-locale.R")
  log <- tempfile()
  on.exit(unlink(log), add = TRUE)
  status <- system2(file.path(R.home("bin"), "Rscript"),
                    c("--vanilla", shQuote(script), shQuote(.libPaths())),
                    stdout = log, stderr = log)
  if (identical(status, 77L)) skip("no comma-decimal locale is installed")
  expect_identical(status, 0L, info = paste(readLines(log, warn = FALSE), collapse = "\n"))
})

test_that("unexpected Newick tokens identify the missing separator", {
  expect_error(validate_species_tree("(A B,C);"), "expected ',' or '\\)' but found 'B'")
})

test_that("a duplicate split is rejected when the engine authority is created", {
  expect_error(
    .engine002_authority(c("A", "B", "C", "D"), c(NA_integer_, NA_integer_),
                         list(as.raw(3), as.raw(3))),
    "duplicate primitive splits"
  )
})

test_that("a failed post-link publish can be retried with the same store ID", {
  skip_on_os("windows")  # Windows uses a single no-replace move.
  directory <- tempfile()
  dir.create(directory)
  directory <- normalizePath(directory, mustWork = TRUE)
  on.exit(unlink(directory, recursive = TRUE), add = TRUE)
  id <- strrep("a", 32L)
  build <- function() cpp_engine002_build_authority_scale_store(
    directory, id, 1, 2^20, 2^20, 2^20, 2^20, 4 * 2^20
  )
  cpp_engine002_set_publication_failpoint(16L)
  on.exit(cpp_engine002_set_publication_failpoint(0L), add = TRUE)
  expect_error(build(), "injected publication failpoint")
  expect_length(list.files(directory, all.files = TRUE, no.. = TRUE), 0L)
  cpp_engine002_set_publication_failpoint(0L)
  result <- build()
  expect_true(file.exists(result$manifest))
  expect_identical(result$pattern_count, 1)
  expect_gt(result$index_charged_bytes, 0)
})
