test_that("shared columns use exactly the complete current components", {
  species <- "(((((A,B),C),D),E),F,(G,H));"
  genes <- test_path("fixtures", "whole-component-genes.nwk")
  target <- "F[B9|B10|B11]"
  whole <- align_branches(species, genes)
  direct <- align_branches(species, genes, fusion_view = "direct")
  cell <- fusion_cells(whole, coordinate_ids = target)
  expected <- c(15, 15, 15, NA, NA, NA, NA, 0, NA, 15, NA)
  expect_identical(cell$numeric_value, expected)
  expect_identical(unname(whole$numeric_matrix[, target]), expected)
  expect_identical(cell$construction_mode[1:3],
                   c("selected_component_edge_sum", "selected_component_edge_sum", "single_edge_lookup"))
  expect_identical(cell$numeric_status[6:9], c("not_recovered", "missing_length", "available", "not_recovered"))
  expect_identical(cell$recovery_status[7], "recovered")
  expect_identical(cell$reference_state[c(4, 5, 9)], c("unavailable", "unavailable", "active"))
  expect_identical(cell$reference_reason[4:5], c("partial_component", "deleted_member_and_partial_component"))
  parts <- cell$components[[2]]
  expect_identical(unclass(parts$primitive_members), list(c("B9","B10"), "B11"))
  expect_identical(parts$numeric_value, c(8, 7))
  expect_identical(parts$source_nodes, c("2", "4"))
  expect_identical(parts$projected_split, c("A..B||D..E..F..G..H", "A..B..D||E..F..G..H"))
  expect_identical(length(strsplit(cell$components[[10]]$source_nodes, ",")[[1L]]), 2L)
  expect_true(all(is.na(whole$numeric_matrix["pair", c("B9", "B10")])))
  expect_identical(unname(direct$numeric_matrix[, target]), ifelse(cell$reference_state == "active", expected, NA_real_))
  for (key in c("state_matrix", "state_ledger", "composite_ledger", "support_table", "support_newick"))
    expect_identical(whole[[key]], direct[[key]])
  expect_identical(count_free_topology(whole, "coordinate"), count_free_topology(direct, "coordinate"))
  expect_identical(fusion_cells(direct, "pair", target)$numeric_status, "direct_only")
  expect_identical(fusion_cells(whole, c("pair", "pair"), target)$numeric_value, c(15, 15))
  # Old direct-only result files retain their stored values and remain readable.
  old <- direct
  old$metadata[c("fusion_schema", "fusion_view")] <- NULL
  old$state_ledger$source_nodes <- NULL
  old$composite_ledger$source_nodes <- NULL
  path <- tempfile()
  saveRDS(old, path)
  expect_identical(read_splitaligner_result(path), old)
  expect_error(fusion_cells(old), "Rerun")
})


test_that("fusion provenance refuses reordered or inconsistent result ledgers", {
  ref <- "((A,B),C,(D,(E,F)));"
  trees <- c(g1 = "((A:1,B:2):3,D:4,(E:5,F:6):7);",
             g2 = "((A:1,B:2):3,C:4,(D:5,(E:6,F:7):8):9);")
  target <- "F[B7|B9]"
  for (mode in c("free", "fixed")) {
    x <- align_branches(ref, trees, mode = mode)
    expect_identical(fusion_cells(x)$numeric_value, c(3, 12))
    bad <- x
    bad$state_ledger <- bad$state_ledger[rev(seq_len(nrow(bad$state_ledger))), ]
    expect_error(fusion_cells(bad), "state ledger is not the complete unique")
    bad <- x
    bad$composite_ledger$projected_split[1] <- "A||B..D..E..F"
    expect_error(fusion_cells(bad), "projected split or composite membership")
    bad <- x
    bad$numeric_matrix["g2", target] <- 999
    expect_error(fusion_cells(bad, "g2"), "fusion source evidence")
    expect_identical(fusion_cells(bad, "g1")$numeric_value, 3)
    expect_equal(nrow(fusion_cells(x, coordinate_ids = character())), 0L)
  }
})
