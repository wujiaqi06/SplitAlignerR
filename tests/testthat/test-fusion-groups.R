test_that("Figure 4 records a topology loss on the shared group only", {
  species <- "((A,B),C,(D,(E,F)));"
  genes <- c(g1 = "((A,B):0.31,D,(E,F):0.17);",
             g2 = "((A,B):0.26,E,(D,F));",
             g3 = "((A,D),B,(E,F):0.23);")
  free <- align_branches(species, genes, mode = "free")
  fixed <- align_branches(species, rep(unname(genes[1]), 3),
                          gene_ids = names(genes), mode = "fixed")
  paired <- pair_alignment_results(fixed, free)
  groups <- free_fusion_groups(free)
  expect_identical(paired$free_fusion_groups, groups)
  expect_identical(groups$gene_id, names(genes))
  expect_length(unique(groups$composite_id), 1)
  expect_identical(groups$primitive_members[[1]], groups$primitive_members[[3]])
  members <- groups$primitive_members[[1]]
  expect_length(members, 2)
  expect_true(all(paired$final_matrix[, members] == "NA_fuse"))
  expect_true(all(paired$fixed_final_matrix[, members] == "NA_fuse"))
  expect_false(any(paired$final_matrix == "NA_fuse_topo"))
  expect_identical(groups$graph_class, c("Mapped", "Mapped", "NA_fuse_topo"))
  expect_equal(as.numeric(groups$final_token[1:2]), c(0.31, 0.26))
  expect_identical(groups$final_token[3], "NA_fuse_topo")
  expect_identical(groups$numeric_value[3], NA_real_)
  legacy <- pair_alignment_results(fixed, free, rule = "legacy")
  expect_true(all(legacy$final_matrix["g3", members] == "NA"))
  expect_identical(legacy$metadata$paired_schema, "1.0.0")
  expect_error(free_fusion_groups(fixed), "free-mode")
})

test_that("group presence is independent of numeric evidence and resolution", {
  species <- "((A,B),C,(D,(E,F)));"
  free <- align_branches(species, c(no_length = "((A,B),D,(E,F));",
                                    zero = "((A,B):0,D,(E,F));",
                                    star = "(A,B,D,E,F);"))
  fixed <- align_branches(species, rep("((A,B),D,(E,F));", 3),
                          mode = "fixed", gene_ids = rownames(free$state_matrix))
  groups <- free_fusion_groups(free)
  expect_identical(groups$graph_class, c("Mapped", "Mapped", "NA_fuse_topo"))
  expect_identical(groups$final_token, c("NA", "0", "NA_fuse_topo"))
  paired <- pair_alignment_results(fixed, free)
  expect_true(all(paired$final_matrix[, groups$primitive_members[[1]]] == "NA_fuse"))
  expect_true(all(paired$fixed_final_matrix[, groups$primitive_members[[1]]] == "NA_fuse"))
  expect_identical(paired$free_fusion_groups, groups)
  empty <- free_fusion_groups(align_branches("(A,B,C);", "(A,B,C);"))
  expect_identical(nrow(empty), 0L)
  expect_identical(empty$graph_class, character())
  bad <- free
  bad$composite_ledger$recovery_status[1] <- "unrecovered"
  expect_error(free_fusion_groups(bad), "recovery evidence")
  bad <- free
  bad$composite_ledger$projected_split[1] <- "another split"
  expect_error(free_fusion_groups(bad), "projected split")
  bad$state_ledger$projected_split[bad$state_ledger$gene_id == "no_length" &
                                  bad$state_ledger$state == "NA_fuse"] <- "another split"
  expect_error(pair_alignment_results(fixed, bad), "members or projected splits")
})

test_that("five outcome counts distinguish primitive and coordinate denominators", {
  ref <- "((A,B),C,(D,(E,F)));"
  trees <- c(all_present = ref,
             g1 = "((A,B),D,(E,F));",
             g2 = "((A,B),E,(D,F));",
             g3 = "((A,D),B,(E,F));")
  free <- align_branches(ref, trees)
  before <- free$state_matrix
  primitive <- count_free_topology(free, unit = "primitive")
  coordinate <- count_free_topology(free, unit = "coordinate")
  expect_identical(primitive$gene_id, names(trees))
  expect_identical(coordinate$gene_id, names(trees))
  expect_identical(primitive$unit, rep("primitive", 4))
  expect_identical(coordinate$unit, rep("coordinate", 4))
  expect_equal(primitive$Total, c(9, 9, 9, 9))
  expect_equal(coordinate$Total, c(9, 8, 8, 8))
  expect_equal(primitive$Mapped, c(9, 6, 5, 6))
  expect_equal(primitive$NA_struct, c(0, 1, 1, 1))
  expect_equal(primitive$NA_topo, c(0, 0, 1, 0))
  expect_equal(primitive$NA_fuse, c(0, 2, 2, 0))
  expect_equal(primitive$NA_fuse_topo, c(0, 0, 0, 2))
  expect_equal(coordinate$NA_fuse, c(0, 1, 1, 0))
  expect_equal(coordinate$NA_fuse_topo, c(0, 0, 0, 1))
  for (counts in list(primitive, coordinate)) {
    expect_equal(counts$Total, unname(rowSums(counts[4:8])))
  }
  expect_identical(free$state_matrix, before)
  expect_error(count_free_topology(free), "Choose unit")
  expect_error(count_free_topology(free, "prim"), "Choose unit")
  expect_error(count_free_topology(free, NA_character_), "Choose unit")
  expect_error(count_free_topology(align_branches(ref, ref, mode="fixed"),
                                   "primitive"), "free-mode")
})

test_that("group weights follow each fiber across different retained taxa", {
  ref <- "((A,B),C,(D,(E,F)));"
  free <- align_branches(ref, c(long_path = "(A,F);",
                                two_groups = "((A,D),(B,E));"))
  primitive <- count_free_topology(free, "primitive")
  coordinate <- count_free_topology(free, "coordinate")
  # A--F collapses five primitive edges onto one displayed split.
  # The four-taxon gene has one displayed and one absent two-member group.
  expect_equal(primitive$NA_fuse, c(5, 2))
  expect_equal(primitive$NA_fuse_topo, c(0, 2))
  expect_equal(coordinate$NA_fuse, c(1, 1))
  expect_equal(coordinate$NA_fuse_topo, c(0, 1))
  expect_equal(primitive$NA_struct, c(4, 2))
  expect_equal(coordinate$Total, c(5, 7))
})
