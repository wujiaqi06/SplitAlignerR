test_that("direct fusion cells suppress sums before component length checks", {
  reference <- "((A,(B,C)),(D,E));"
  genes <- test_path("fixtures", "direct-view-genes.nwk")
  whole <- align_branches(reference, genes, fusion_view = "whole")
  direct <- align_branches(reference, genes, fusion_view = "direct")
  target <- "F[B2|B6]"
  w <- fusion_cells(whole, coordinate_ids = target)
  d <- fusion_cells(direct, coordinate_ids = target)
  expect_identical(w$numeric_status,
                   c("available", "nonfinite_sum", "missing_length", "available",
                     "available", "not_recovered", "not_applicable", "missing_length"))
  expect_identical(d$numeric_status,
                   c("available", "direct_only", "direct_only", "direct_only",
                     "direct_only", "not_recovered", "not_applicable", "missing_length"))
  expect_identical(w$numeric_value, c(1, NA, NA, 0, 5, NA, NA, NA))
  expect_identical(d$numeric_value, c(1, rep(NA_real_, 7)))
  expect_identical(unname(direct$numeric_matrix[, target]), d$numeric_value)
  for (field in c("reference_state", "reference_reason", "recovery_status",
                  "construction_mode", "components")) {
    expect_identical(d[[field]], w[[field]])
  }
  missing_parts <- d$components[[which(d$gene_id == "missing")]]
  expect_true(anyNA(missing_parts$numeric_value))
  expect_true(all(missing_parts$recovery_status == "recovered"))
  expect_true(all(nzchar(missing_parts$source_nodes)))
  for (field in c("state_matrix", "state_ledger", "composite_ledger", "support_table",
                  "support_newick")) {
    expect_identical(direct[[field]], whole[[field]])
  }
  expect_identical(count_free_topology(direct, "coordinate"),
                   count_free_topology(whole, "coordinate"))
  expect_identical(count_free_topology(direct, "primitive"),
                   count_free_topology(whole, "primitive"))
})

test_that("direct view still rejects overflow while normalizing one unrooted observation", {
  reference <- "((A,(B,C)),(D,E));"
  gene <- c(bad = "(A:1e308,(B:1,C:1,D:1,E:1):1e308);")
  for (view in c("whole", "direct")) {
    expect_error(align_branches(reference, gene, fusion_view = view),
                 "overflow|not finite")
  }
})
