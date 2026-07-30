test_that("runtime package, core, general schema, and paired schema are consistent", {
  expect_identical(as.character(packageVersion("SplitAlignerR")), "0.1.0.9000")
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

test_that("development identity preserves the certified v0.1.0 boundary", {
  identity_path <- system.file(
    "recert", "RELEASE_IDENTITY.json", package = "SplitAlignerR"
  )
  expect_true(nzchar(identity_path))
  identity <- paste(readLines(identity_path, warn = FALSE), collapse = "\n")

  expect_match(identity, '"certified_release_tag": "v0.1.0"', fixed = TRUE)
  expect_match(
    identity,
    '"certified_release_commit": "17a0927095c7a067817bf598a2556cbe7348a6d0"',
    fixed = TRUE
  )
  expect_match(identity, '"development_version": "0.1.0.9000"', fixed = TRUE)
  expect_match(
    identity,
    '"development_status": "post-release development"',
    fixed = TRUE
  )
  expect_match(
    identity,
    '"recert_status": "not covered by v0.1.0 Pro PASS"',
    fixed = TRUE
  )
})
