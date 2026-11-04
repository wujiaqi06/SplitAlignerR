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
