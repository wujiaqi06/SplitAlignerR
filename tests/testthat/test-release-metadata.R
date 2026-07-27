test_that("runtime package, core, general schema, and paired schema are consistent", {
  expect_identical(as.character(packageVersion("SplitAlignerR")), "0.1.0")
  core <- splitaligner_core_info()
  expect_identical(core$core_version, "0.1.0")
  expect_identical(core$schema_version, "1.0.0")

  species <- "((A:1,B:1):1,(C:1,D:1):1);"
  fixed <- align_branches(species, c(g = species), mode = "fixed")
  free <- align_branches(species, c(g = species), mode = "free")
  paired <- pair_alignment_results(fixed, free)
  expect_identical(paired$metadata$core_version, "0.1.0")
  expect_identical(paired$metadata$schema_version, "1.0.0")
  expect_identical(paired$metadata$paired_schema, "1.0.0")
})
