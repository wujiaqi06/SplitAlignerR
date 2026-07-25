test_that("package release-candidate status helper returns a single string", {
  s <- splitalignerR_scaffold()
  expect_type(s, "character")
  expect_length(s, 1)
  expect_match(s, "V1 release candidate")
  expect_match(s, "not a final release certificate")
})

test_that("catnip10_expected returns the expected 8 x 18 matrices", {
  for (regime in c("global", "local")) {
    m <- catnip10_expected(regime)
    expect_s3_class(m, "data.frame")
    expect_identical(nrow(m), 8L)
    expect_identical(ncol(m), 18L)
    expect_true("gene_id" %in% names(m))
    coords <- c(paste0("t", 1:10), paste0("N_", 12:18))
    expect_true(all(coords %in% names(m)))
  }
})

test_that("catnip10 accessors validate arguments and return bundled tables", {
  expect_error(catnip10_expected("nope"))
  expect_error(catnip10_matrix("nope"))
  expect_error(catnip10_fusion_groups("nope"))

  groups <- catnip10_fusion_groups()
  expect_s3_class(groups, "data.frame")
  expect_true(all(c("regime", "gene_id", "benchmark_unrooted_members") %in% names(groups)))
  expect_gt(nrow(groups), 0L)

  local_matrix <- catnip10_matrix("local")
  expect_s3_class(local_matrix, "data.frame")
  expect_identical(dim(local_matrix), c(8L, 18L))
})

test_that("catnip10_summary_counts returns required accounting columns", {
  counts <- catnip10_summary_counts()
  expect_s3_class(counts, "data.frame")
  expect_true(all(c("regime", "observed", "NA_fuse", "NA_struct", "NA_topo", "total") %in% names(counts)))
  expect_identical(counts$regime, c("global", "local"))
  expect_true(all(counts$total == 136L))
  expect_true(all(counts$NA_topo == 0L))
})

test_that("validate_catnip10_oracle reruns both pure R oracle scenarios", {
  checks <- validate_catnip10_oracle()
  expect_s3_class(checks, "data.frame")
  expect_true(all(c("check", "status", "details") %in% names(checks)))
  expect_true(all(checks$status %in% c("PASS", "DEFERRED")))
  expect_false(any(checks$status == "FAIL"))
  oracle_checks <- checks[grepl("^pure_R_graph_oracle_exact_", checks$check), ]
  expect_identical(oracle_checks$check, c(
    "pure_R_graph_oracle_exact_global",
    "pure_R_graph_oracle_exact_local"
  ))
  expect_true(all(oracle_checks$status == "PASS"))
  expect_true(all(grepl("136/136", oracle_checks$details, fixed = TRUE)))
})

test_that("bundled oracle has both regimes and no NA_topo", {
  expect_true(all(c("global", "local") %in% names(catnip10_oracle)))
  for (regime in c("global", "local")) {
    m <- catnip10_oracle[[regime]]$matrix
    expect_false(any(vapply(m, function(col) any(col == "NA_topo"), logical(1))))
  }
})

test_that("public metadata does not contain fake DOI or private path placeholders", {
  citation_path <- test_path("../../CITATION.cff")
  readme_path <- test_path("../../README.md")
  if (!file.exists(citation_path) || !file.exists(readme_path)) {
    skip("Source-root public metadata files are not available in installed-package tests")
  }

  citation <- readLines(citation_path, warn = FALSE)
  readme <- readLines(readme_path, warn = FALSE)
  public_text <- c(citation, readme)
  placeholder <- paste0("PLACE", "HOLDER")
  fake_zenodo <- paste0("10[.]5281/zenodo[.]", placeholder)
  private_path_pattern <- paste0(
    "/Us", "ers/|/ho", "me/|Docu", "ments/|Bird_", "mammal"
  )

  expect_false(any(grepl(paste(placeholder, fake_zenodo, sep = "|"), public_text)))
  expect_false(any(grepl(private_path_pattern, public_text)))
  expect_false(any(grepl("only a placeholder scaffold", readme, ignore.case = TRUE)))
  expect_true(any(grepl("Catnip10 graph-oracle benchmark", readme, fixed = TRUE)))
})

test_that("align_branches() requires explicit tree inputs", {
  expect_error(align_branches(), "species_tree.*missing|argument.*missing")
})
