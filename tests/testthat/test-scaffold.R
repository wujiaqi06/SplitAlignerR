test_that("scaffold placeholder returns a single string", {
  s <- splitalignerR_scaffold()
  expect_type(s, "character")
  expect_length(s, 1)
  expect_match(s, "scaffold")
})

test_that("catnip10_expected returns the expected 8 x 18 matrices", {
  for (regime in c("global", "local")) {
    m <- catnip10_expected(regime)
    expect_s3_class(m, "data.frame")
    expect_identical(nrow(m), 8L)
    expect_identical(ncol(m), 18L)
    expect_true("gene_id" %in% names(m))
    # 17 primitive coordinates present
    coords <- c(paste0("t", 1:10), paste0("N_", 12:18))
    expect_true(all(coords %in% names(m)))
  }
})

test_that("catnip10_expected validates the regime argument", {
  expect_error(catnip10_expected("nope"))
})

test_that("bundled oracle has both regimes and the benchmark truth identity holds", {
  expect_true(all(c("global", "local") %in% names(catnip10_oracle)))
  # NA_topo never arises in this discordance-free benchmark
  for (regime in c("global", "local")) {
    m <- catnip10_oracle[[regime]]$matrix
    expect_false(any(vapply(m, function(col) any(col == "NA_topo"), logical(1))))
  }
})
