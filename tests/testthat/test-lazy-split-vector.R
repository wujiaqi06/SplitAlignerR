.lazy_split_example <- function() {
  align_branches("(A:1,B:2,C:3,D:4);",
                 c(full = "(A:1,B:2,C:3,D:4);", drop = "(A:1,C:3,D:4);"))
}

.lazy_split_expected <- function() {
  c("A||B..C..D", "A..C..D||B", "A..B..D||C", "A..B..C||D",
    "A||C..D", NA_character_, "A..D||C", "A..C||D")
}

.lazy_split_inspect <- function(x) paste(capture.output(.Internal(inspect(x))), collapse = "\n")

test_that("split audit columns remain ordinary lazy character vectors", {
  result <- .lazy_split_example()
  x <- result$state_ledger$projected_split
  expected <- .lazy_split_expected()
  expect_type(x, "character")
  expect_null(attributes(x))
  expect_match(.lazy_split_inspect(x), "materialized=no", fixed = TRUE)
  expect_identical(x, expected)
  expect_identical(x[[1]], expected[[1]])
  expect_true(anyNA(x))
  expect_false(anyNA(x[1:4]))
  expect_identical(is.na(x), is.na(expected))
  expect_identical(capture.output(print(x)), capture.output(print(expected)))
  # Reading, comparing and printing must not leave an expanded vector behind.
  expect_match(.lazy_split_inspect(x), "materialized=no", fixed = TRUE)
  rm(result)
  invisible(gc())
  expect_identical(x, expected)
})

test_that("lazy split subsets retain character indexing and attributes", {
  x <- .lazy_split_example()$state_ledger$projected_split
  expected <- .lazy_split_expected()
  selections <- list(integer(), rev(seq_along(x)), c(1L, NA_integer_, 99L, 1L),
                     c(1, 3, NA_real_, Inf), c(0.9, 1.9, 2.1, 8.9),
                     -c(2.1, 4.9), -c(2L, 4L),
                     c(TRUE, FALSE), c(TRUE, NA, FALSE), c(0L, 3L, 0L))
  for (selection in selections) {
    selected <- x[selection]
    expect_identical(selected, expected[selection])
    expect_match(.lazy_split_inspect(selected), "materialized=no", fixed = TRUE)
  }
  expect_identical(x[1.9], expected[1.9])
  expect_identical(x[length(x) + 0.9], expected[length(expected) + 0.9])
  names(x) <- names(expected) <- paste0("r", seq_along(x))
  expect_identical(x[c("r3", "missing", "r1")], expected[c("r3", "missing", "r1")])
  expect_identical(unname(x), unname(expected))
  expect_match(.lazy_split_inspect(x), "materialized=no", fixed = TRUE)
})

test_that("copy-on-modify leaves other lazy split columns unchanged", {
  x <- .lazy_split_example()$state_ledger$projected_split
  expected <- .lazy_split_expected()
  y <- x
  y[1:2] <- c("replacement", NA_character_)
  changed <- expected
  changed[1:2] <- c("replacement", NA_character_)
  expect_identical(x, expected)
  expect_identical(y, changed)
  expect_identical(y[c(2L, 1L, NA_integer_)], changed[c(2L, 1L, NA_integer_)])
  expect_identical(y[c(1.9, 2.1, length(y) + 0.9)],
                   changed[c(1.9, 2.1, length(changed) + 0.9)])
  z <- y
  z[1] <- "second replacement"
  expect_identical(y, changed)
  expect_identical(x, expected)
  expect_match(.lazy_split_inspect(x), "materialized=no", fixed = TRUE)
  expect_identical(unserialize(serialize(y, NULL, version = 3)), changed)
})

test_that("both split ledgers serialize compactly and retain public values", {
  ref <- "((A,B),C,(D,(E,F)));"
  trees <- c(g1 = "((A:1,B:2):3,D:4,(E:5,F:6):7);",
             g2 = "((A:1,B:2):3,C:4,(D:5,(E:6,F:7):8):9);")
  result <- align_branches(ref, trees)
  for (ledger in c("state_ledger", "composite_ledger")) {
    x <- result[[ledger]]$projected_split
    expect_gt(length(x), 0L)
    expect_match(.lazy_split_inspect(x), "materialized=no", fixed = TRUE)
    restored <- unserialize(serialize(x, NULL, version = 3))
    expect_identical(restored, x)
    expect_match(.lazy_split_inspect(restored), "materialized=no", fixed = TRUE)
    # R 3.5's version-2 serialization remains readable as ordinary strings.
    old_format <- unserialize(serialize(x, NULL, version = 2))
    expect_identical(old_format, x)
    expect_false(grepl("splitaligner_lazy_split_v1", .lazy_split_inspect(old_format), fixed = TRUE))
    expect_match(.lazy_split_inspect(x), "materialized=no", fixed = TRUE)
  }
  restored_result <- unserialize(serialize(result, NULL, version = 3))
  expect_identical(restored_result, result)
  expect_identical(fusion_cells(restored_result), fusion_cells(result))
})

test_that("a focused fusion query leaves both full split ledgers deferred", {
  result <- align_branches("(((((A,B),C),D),E),F,(G,H));",
                           test_path("fixtures", "whole-component-genes.nwk"))
  cell <- fusion_cells(result, gene_ids = "pair", coordinate_ids = "F[B9|B10|B11]")
  expect_identical(cell$numeric_value, 15)
  components <- cell$components[[1]]
  expect_identical(unclass(components$primitive_members), list(c("B9", "B10"), "B11"))
  expect_identical(components$numeric_value, c(8, 7))
  expect_identical(components$source_nodes, c("2", "4"))
  expect_identical(components$projected_split,
                   c("A..B||D..E..F..G..H", "A..B..D||E..F..G..H"))
  for (ledger in c("state_ledger", "composite_ledger")) {
    expect_match(.lazy_split_inspect(result[[ledger]]$projected_split),
                 "materialized=no", fixed = TRUE)
  }
})

test_that("saved lazy splits reload in a fresh process and load their namespace", {
  installed <- find.package("SplitAlignerR")
  skip_if_not(file.exists(file.path(installed, "Meta", "package.rds")),
              "Fresh-process check requires an installed package")
  script <- tempfile(fileext = ".R")
  input <- tempfile(fileext = ".rds")
  oracle <- tempfile(fileext = ".rds")
  on.exit(unlink(c(script, input, oracle)), add = TRUE)
  saveRDS(.lazy_split_example()$state_ledger$projected_split, input, version = 3)
  saveRDS(.lazy_split_expected(), oracle, version = 2)
  writeLines(c(
    "args <- commandArgs(TRUE)",
    ".libPaths(c(args[1], .libPaths()))",
    "stopifnot(!'SplitAlignerR' %in% loadedNamespaces())",
    "if (args[4] == 'explicit') library(SplitAlignerR)",
    "x <- readRDS(args[2])",
    "stopifnot('SplitAlignerR' %in% loadedNamespaces())",
    "stopifnot(identical(x, readRDS(args[3])))",
    "invisible(gc())",
    "stopifnot(identical(x[c(8L, NA_integer_, 1L)], readRDS(args[3])[c(8L, NA_integer_, 1L)]))",
    "state <- paste(capture.output(.Internal(inspect(x))), collapse='\\n')",
    "stopifnot(grepl('materialized=no', state, fixed=TRUE))",
    "cat('FRESH_SPLIT_ROUNDTRIP_OK\\n')"
  ), script)
  for (mode in c("autoload", "explicit")) {
    output <- system2(file.path(R.home("bin"), "Rscript"),
                      shQuote(c("--vanilla", script, dirname(installed), input, oracle, mode)),
                      stdout = TRUE, stderr = TRUE)
    expect_null(attr(output, "status"), info = paste(output, collapse = "\n"))
    expect_true(any(output == "FRESH_SPLIT_ROUNDTRIP_OK"),
                info = paste(output, collapse = "\n"))
  }
})

test_that("compact serialization scales with bit records rather than display text", {
  # Different retained sets prevent R's serialized string deduplication from
  # hiding the cost of an eagerly expanded projected-split audit column.
  taxa <- paste0("taxon_", seq_len(24L), "_", paste(rep("x", 60L), collapse = ""))
  star <- function(labels) paste0("(", paste0(labels, ":1", collapse = ","), ");")
  trees <- vapply(seq_len(12L), function(i) star(taxa[-i]), character(1))
  names(trees) <- paste0("g", seq_along(trees))
  x <- align_branches(star(taxa), trees)$state_ledger$projected_split
  compact <- serialize(x, NULL, version = 3)
  ordinary <- serialize(x, NULL, version = 2)
  expect_lt(length(compact), length(ordinary) / 3)
  expect_identical(unserialize(compact), unserialize(ordinary))
})

test_that("compact RDS preserves Unicode across a change in native locale", {
  installed <- find.package("SplitAlignerR")
  skip_if_not(file.exists(file.path(installed, "Meta", "package.rds")),
              "Fresh-process check requires an installed package")
  skip_if_not(isTRUE(l10n_info()[["UTF-8"]]),
              "This producer-side regression requires a UTF-8 native locale")
  ref <- paste0("((", intToUtf8(233L), ",B),C,(D,", intToUtf8(945L), "));")
  x <- align_branches(ref, ref)$state_ledger$projected_split
  ordinary <- unserialize(serialize(x, NULL, version = 2))
  expect_identical(Encoding(x), Encoding(ordinary))
  expect_identical(unserialize(serialize(x, NULL, version = 3)), ordinary)
  script <- tempfile(fileext = ".R")
  input <- tempfile(fileext = ".rds")
  oracle <- tempfile(fileext = ".rds")
  returned <- tempfile("split-locale-return-")
  dir.create(returned)
  on.exit(unlink(c(script, input, oracle, returned), recursive = TRUE), add = TRUE)
  writeLines(ref, file.path(returned, "reference.nwk"))
  saveRDS(x, input, version = 3)
  saveRDS(ordinary, oracle, version = 3)
  writeLines(c(
    "args <- commandArgs(TRUE)",
    ".libPaths(c(args[1], .libPaths()))",
    "stopifnot(nzchar(Sys.setlocale('LC_CTYPE', 'C')))",
    "x <- readRDS(args[2])",
    # R may warn when its ordinary native strings require UTF-8 fallback.
    "y <- suppressWarnings(readRDS(args[3]))",
    "stopifnot(identical(x, y), identical(nchar(x), nchar(y)))",
    "stopifnot(identical(enc2utf8(x), enc2utf8(y)))",
    "stopifnot(identical(x[c(7L, 1L, NA_integer_)], y[c(7L, 1L, NA_integer_)]))",
    "state <- paste(capture.output(.Internal(inspect(x))), collapse='\\n')",
    "stopifnot(grepl('materialized=no', state, fixed=TRUE))",
    "again <- unserialize(serialize(x, NULL, version=3))",
    "stopifnot(identical(again, y), identical(nchar(again), nchar(y)))",
    "path <- file.path(args[4], 'reference.nwk')",
    "direct <- SplitAlignerR::align_branches(path, path)$state_ledger$projected_split",
    "direct_ordinary <- unserialize(serialize(direct, NULL, version=2))",
    "cases <- list(restored=list(x, y), direct=list(direct, direct_ordinary))",
    "for (name in names(cases)) {",
    "  lazy <- cases[[name]][[1]]; ordinary <- cases[[name]][[2]]",
    "  expanded <- lazy; expanded[1] <- expanded[1]",
    "  stopifnot(identical(lazy, ordinary), identical(Encoding(lazy), Encoding(expanded)))",
    "  saveRDS(lazy, file.path(args[4], paste0(name, '-lazy.rds')), version=3)",
    "  saveRDS(expanded, file.path(args[4], paste0(name, '-expanded.rds')), version=3)",
    "  saveRDS(ordinary, file.path(args[4], paste0(name, '-ordinary.rds')), version=3)",
    "}",
    "cat('CROSS_LOCALE_SPLIT_OK\\n')"
  ), script)
  output <- system2(file.path(R.home("bin"), "Rscript"),
                    shQuote(c("--vanilla", script, dirname(installed), input, oracle, returned)),
                    stdout = TRUE, stderr = TRUE)
  expect_null(attr(output, "status"), info = paste(output, collapse = "\n"))
  expect_true(any(output == "CROSS_LOCALE_SPLIT_OK"),
              info = paste(output, collapse = "\n"))
  for (name in c("restored", "direct")) {
    lazy <- readRDS(file.path(returned, paste0(name, "-lazy.rds")))
    expanded <- readRDS(file.path(returned, paste0(name, "-expanded.rds")))
    ordinary <- readRDS(file.path(returned, paste0(name, "-ordinary.rds")))
    expect_identical(lazy, ordinary)
    expect_identical(expanded, ordinary)
    expect_identical(Encoding(lazy), Encoding(ordinary))
    expect_identical(Encoding(expanded), Encoding(ordinary))
    expect_identical(nchar(lazy), nchar(ordinary))
    expect_match(.lazy_split_inspect(lazy), "materialized=no", fixed = TRUE)
  }
})
