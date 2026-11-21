test_that("new S4 schema retains frozen unrooted whole and direct semantics", {
  # Frozen before the observation-schema change. Compare independent original
  # states, numerical values, memberships and source counts, not schema names,
  # observation IDs or hashes that are allowed to change across representations.
  frozen <- readRDS(test_path("fixtures", "s4-assembly-9007.rds"))
  expect_identical(frozen$source_commit, "30773f047a60ccd6070d0c8940bad0a6041f9904")
  key <- function(gene, members) paste(gene,
    vapply(members, paste, character(1), collapse = "|"), sep = "\r")
  for (view in c("whole", "direct")) {
    expected <- frozen[[view]]
    actual <- align_fixed_topology(frozen$species, frozen$genes, fusion_view = view)
    states <- expected$state_matrix
    states[states == "mapped"] <- "observed"
    expect_identical(actual$reference_state_matrix, states)
    expect_equal(actual$numeric_matrix, expected$numeric_matrix, tolerance = 1e-12)
    expect_identical(actual$primitive_coordinates, expected$primitive_coordinates)
    expect_identical(actual$composite_coordinates, expected$composite_coordinates)
    legacy <- expected$component_ledger
    reference <- actual$reference_components
    i <- match(key(legacy$gene_id, legacy$primitive_members),
               key(reference$gene_id, reference$primitive_members))
    expect_false(anyNA(i))
    expect_identical(reference$primitive_members[i], legacy$primitive_members)
    observations <- actual$observation_ledger
    i <- match(key(legacy$gene_id, legacy$primitive_members),
               key(observations$gene_id, observations$primitive_members))
    expect_false(anyNA(i))
    expect_equal(observations$numeric_value[i], legacy$numeric_value, tolerance = 1e-12)
    expect_identical(observations$numeric_status[i], legacy$numeric_status)
    expect_identical(lengths(observations$input_edge_ids[i]), lengths(legacy$source_nodes))
    expect_identical(actual$fusion_ledger$reference_state, expected$fusion_ledger$reference_state)
    expect_identical(actual$fusion_ledger$reference_reason, expected$fusion_ledger$reference_reason)
    expect_equal(actual$fusion_ledger$numeric_value, expected$fusion_ledger$numeric_value, tolerance = 1e-12)
    expect_identical(actual$metadata$result_schema, "s4-observation-v1")
    expect_false(any(c("state_matrix", "component_ledger") %in% names(actual)))
    expect_equal(actual$metadata$n_success, nrow(expected$state_matrix))
    expect_equal(actual$metadata$n_skipped_topology, 0L)
  }
})
