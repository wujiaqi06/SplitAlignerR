test_that("finite fixed primitive evidence promotes generic NA", {
  finalized <- SplitAlignerR:::finalize_paired_tokens(
    c("0", "-0", "1.2e-8"), "NA"
  )
  expect_identical(
    finalized$final_matrix_token,
    rep("NA_topo", 3L)
  )
  expect_true(all(finalized$fixed_primitive_numeric_available))
})

test_that("generic fixed and free NA finalize as NA_struct", {
  finalized <- SplitAlignerR:::finalize_paired_tokens("NA", "NA")
  expect_identical(finalized$final_matrix_token, "NA_struct")
  expect_identical(finalized$summary_class, "NA_struct")
})

test_that("nonnumeric fixed primitive states never promote NA_topo", {
  fixed <- c("NA_fuse", "NA_struct", "NA_topo", "NA_other",
             "NaN", "Inf", "-Inf")
  finalized <- SplitAlignerR:::finalize_paired_tokens(fixed, "NA")
  expect_identical(finalized$final_matrix_token, rep("NA", length(fixed)))
  expect_false(any(finalized$fixed_primitive_numeric_available))
  expect_identical(finalized$summary_class, rep("residual_NA", length(fixed)))

  expect_error(
    SplitAlignerR:::finalize_paired_tokens("", "NA"),
    "Empty or whitespace"
  )
  expect_error(
    SplitAlignerR:::finalize_paired_tokens("   ", "NA"),
    "Empty or whitespace"
  )
  expect_error(
    SplitAlignerR:::finalize_paired_tokens(NA_character_, "NA"),
    "Actual R missing"
  )
})

test_that("fixed fused numeric evidence cannot replace the primitive gate", {
  finalized <- SplitAlignerR:::finalize_paired_tokens(
    "NA_fuse", "NA", fixed_fused_numeric_available = TRUE
  )
  expect_false(finalized$fixed_primitive_numeric_available)
  expect_true(finalized$fixed_fused_numeric_available)
  expect_identical(finalized$final_matrix_token, "NA")
  expect_identical(finalized$summary_class, "residual_NA")
})

test_that("paired result separates graph state, pre-token, and final token", {
  species <- "((A:1,B:1):1,(C:1,D:1):1);"
  fixed <- align_branches(
    species,
    c(g = "((A:1,B:1):1,(C:1,D:1):1);"),
    mode = "fixed"
  )
  free <- align_branches(
    species,
    c(g = "((A:1,C:1):1,(B:1,D:1):1);"),
    mode = "free"
  )
  paired <- pair_alignment_results(fixed, free)

  expect_s3_class(paired, "splitaligner_paired_result")
  expect_identical(paired$semantic_state_matrix["g", "B5"], "NA_topo")
  expect_identical(paired$free_pre_promotion_matrix["g", "B5"], "NA")
  expect_identical(paired$final_matrix["g", "B5"], "NA_topo")
  topo_row <- subset(paired$paired_ledger, coordinate_id == "B5")
  expect_identical(topo_row$fixed_primitive_state, "mapped")
  expect_true(topo_row$fixed_primitive_numeric_available)
  expect_identical(topo_row$free_pre_promotion_token, "NA")
  expect_identical(topo_row$final_matrix_token, "NA_topo")
  expect_identical(topo_row$summary_class, "NA_topo")
  expect_false(topo_row$residual_NA)
})

test_that("mapped nonnumeric free evidence remains literal residual NA", {
  species <- "((A:1,B:1):1,(C:1,D:1):1);"
  fixed <- align_branches(
    species,
    c(g = "((A:1,B:1):1,(C:1,D:1):1);"),
    mode = "fixed"
  )
  free <- align_branches(
    species,
    c(g = "((A:NaN,B:1):1,(C:1,D:1):1);"),
    mode = "free"
  )
  paired <- pair_alignment_results(fixed, free)
  row <- subset(paired$paired_ledger, coordinate_id == "B1")

  expect_identical(row$free_primitive_state, "mapped")
  expect_false(row$free_primitive_numeric_available)
  expect_identical(row$free_pre_promotion_token, "NA")
  expect_identical(row$final_matrix_token, "NA")
  expect_identical(row$summary_class, "residual_NA")
  expect_true(row$residual_NA)
})

test_that("numeric composite evidence yields NA_fuse finalized tokens", {
  species <- "((A:1,B:2):3,(C:4,D:5):6);"
  fixed <- align_branches(species, c(g = "(A:4,B:5);"), mode = "fixed")
  free <- align_branches(species, c(g = "(A:4,B:5);"), mode = "free")
  paired <- pair_alignment_results(fixed, free)

  expect_identical(
    unname(paired$final_matrix["g", c("B1", "B2")]),
    c("NA_fuse", "NA_fuse")
  )
  fused <- subset(paired$paired_ledger, coordinate_id %in% c("B1", "B2"))
  expect_true(all(fused$fixed_fused_numeric_available))
  expect_true(all(fused$free_fused_numeric_available))
  expect_false(any(fused$residual_NA))
})

test_that("fixed fused recovery and free generic NA remain residual NA", {
  species <- paste0(
    "(((A:1,B:1):1,C:1):1,",
    "((D:1,E:1):1,F:1):1);"
  )
  fixed <- align_branches(
    species,
    c(g = "((A:1,B:1):1,(D:1,E:1):1);"),
    mode = "fixed"
  )
  free <- align_branches(
    species,
    c(g = "((A:1,D:1):1,(B:1,E:1):1);"),
    mode = "free"
  )
  paired <- pair_alignment_results(fixed, free)
  residual <- paired$residual_NA

  expect_gt(nrow(residual), 0L)
  expect_true(all(residual$fixed_primitive_state == "NA_fuse"))
  expect_true(all(residual$free_primitive_state == "NA_fuse"))
  expect_true(all(!is.na(residual$fixed_fiber_member_set)))
  expect_true(all(residual$fixed_fused_numeric_available))
  expect_true(all(!residual$fixed_primitive_numeric_available))
  expect_true(all(residual$free_pre_promotion_token == "NA"))
  expect_true(all(residual$final_matrix_token == "NA"))
  expect_true(all(residual$summary_class == "residual_NA"))
})

test_that("fixed primitive numeric unavailability blocks NA_topo promotion", {
  species <- "((A:1,B:1):1,(C:1,D:1):1);"
  fixed <- align_branches(
    species, c(g = "((A:1,B:1),(C:1,D:1));"), mode = "fixed"
  )
  free <- align_branches(
    species, c(g = "((A:1,C:1):1,(B:1,D:1):1);"), mode = "free"
  )
  paired <- pair_alignment_results(fixed, free)
  residual <- subset(paired$residual_NA, coordinate_id == "B5")

  expect_identical(nrow(residual), 1L)
  expect_identical(residual$fixed_primitive_state, "mapped")
  expect_false(residual$fixed_primitive_numeric_available)
  expect_identical(residual$free_primitive_state, "NA_topo")
  expect_identical(residual$free_pre_promotion_token, "NA")
  expect_identical(residual$final_matrix_token, "NA")
  expect_identical(residual$summary_class, "residual_NA")
})

test_that("literal NA survives finalized-matrix round trip", {
  original <- matrix(
    c("NA", "NA_struct", "NA_fuse", "NA_topo", "0", "1.2e-8"),
    nrow = 1L,
    dimnames = list("g", paste0("B", seq_len(6L)))
  )
  SplitAlignerR:::validate_finalized_token_matrix(original)
  path <- tempfile(fileext = ".tsv")
  on.exit(unlink(path), add = TRUE)
  utils::write.table(
    data.frame(gene = rownames(original), original, check.names = FALSE),
    path, sep = "\t", quote = FALSE, row.names = FALSE, na = "NA"
  )
  restored_table <- utils::read.delim(
    path, na.strings = character(0), check.names = FALSE,
    stringsAsFactors = FALSE, colClasses = "character"
  )
  restored <- as.matrix(restored_table[-1L])
  rownames(restored) <- restored_table[[1L]]
  expect_identical(restored, original)
  expect_identical(restored["g", "B1"], "NA")

  invalid <- original
  invalid["g", "B1"] <- NA_character_
  expect_error(
    SplitAlignerR:::validate_finalized_token_matrix(invalid),
    "Actual R missing"
  )
})

test_that("paired results require matched axes, modes, and conventions", {
  species <- "((A,B),(C,D));"
  fixed <- align_branches(species, c(g = "((A:1,B:1),(C:1,D:1));"),
                          mode = "fixed")
  free <- align_branches(species, c(g = "((A:1,B:1),(C:1,D:1));"),
                         mode = "free")
  expect_output(print(pair_alignment_results(fixed, free)),
                "splitaligner_paired_result")
  expect_error(pair_alignment_results(free, fixed), "must come from")

  other_gene <- align_branches(
    species, c(other = "((A:1,B:1),(C:1,D:1));"), mode = "free"
  )
  expect_error(pair_alignment_results(fixed, other_gene), "gene axis")

  other_species <- align_branches(
    "((A,C),(B,D));", c(g = "((A:1,C:1),(B:1,D:1));"), mode = "free"
  )
  expect_error(pair_alignment_results(fixed, other_species), "coordinate axis")
})

test_that("paired results require exact retained taxa for every gene", {
  species <- "((A,B),(C,D));"
  fixed <- align_branches(
    species, c(target = "((A:1,B:1),(C:1,D:1));"), mode = "fixed"
  )
  missing_d <- align_branches(
    species, c(target = "((A:1,B:1),C:1);"), mode = "free"
  )
  expect_error(
    pair_alignment_results(fixed, missing_d),
    "gene `target`.*fixed-only=\\{D\\}.*free-only=\\{<none>\\}"
  )

  reordered <- align_branches(
    species, c(target = "((D:1,C:1),(B:1,A:1));"), mode = "free"
  )
  expect_no_error(pair_alignment_results(fixed, reordered))
  expect_identical(
    fixed$gene_provenance$retained_taxa_key,
    reordered$gene_provenance$retained_taxa_key
  )
})

test_that("matched retained taxa enforce structural fiber invariance", {
  species <- "((A:1,B:2):3,(C:4,D:5):6);"
  fixed <- align_branches(species, c(g = "(A:4,B:5);"), mode = "fixed")
  free <- align_branches(species, c(g = "(A:4,B:5);"), mode = "free")
  free$state_matrix["g", "B1"] <- "NA_topo"
  row <- free$state_ledger$coordinate_id == "B1"
  free$state_ledger$state[row] <- "NA_topo"
  free$state_ledger$reason_code[row] <- "tampered_for_fiber_test"
  free$state_ledger$composite_id[row] <- NA_character_

  expect_error(
    pair_alignment_results(fixed, free),
    "Fiber invariance failed.*gene `g`.*coordinate `B1`"
  )
})
