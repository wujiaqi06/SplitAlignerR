test_that("canonical paired finalizer implements every SEM-003 boundary", {
  finalized <- SplitAlignerR:::finalize_paired_cells(
    fixed_state = c(
      "NA_struct", "mapped", "mapped", "mapped", "NA_fuse", "NA_fuse",
      "mapped"
    ),
    fixed_primitive_numeric = c(NA, NA, 1, 2, NA, NA, 0),
    fixed_fused_numeric = c(NA, NA, NA, NA, 4, NA, NA),
    free_state = c(
      "NA_struct", "NA_topo", "mapped", "NA_topo", "NA_fuse", "NA_fuse",
      "mapped"
    ),
    free_primitive_numeric = c(NA, NA, NA, NA, NA, NA, 1.2e-8),
    free_fused_numeric = c(NA, NA, NA, NA, NA, 5, NA)
  )

  expect_identical(
    finalized$fixed_output_token,
    c("NA_struct", "NA", "1", "2", "NA_fuse", "NA", "0")
  )
  expect_identical(
    finalized$free_pre_promotion_token,
    c("NA", "NA", "NA", "NA", "NA", "NA_fuse", "1.2e-08")
  )
  expect_identical(
    finalized$final_matrix_token,
    c("NA_struct", "NA", "NA", "NA_topo", "NA", "NA_fuse", "1.2e-08")
  )
  expect_identical(
    finalized$summary_class,
    c(
      "NA_struct", "residual_NA", "residual_NA", "NA_topo",
      "residual_NA", "NA_fuse", "numeric"
    )
  )
})

test_that("canonical paired finalizer exhausts legal state-evidence inputs", {
  legal <- data.frame(
    state = c("mapped", "mapped", "NA_struct", "NA_fuse", "NA_fuse",
              "NA_topo"),
    primitive = c(NA, 1, NA, NA, NA, NA),
    fused = c(NA, NA, NA, NA, 2, NA),
    stringsAsFactors = FALSE
  )
  grid <- expand.grid(
    fixed = seq_len(nrow(legal)), free = seq_len(nrow(legal)),
    KEEP.OUT.ATTRS = FALSE
  )
  fixed <- legal[grid$fixed, , drop = FALSE]
  free <- legal[grid$free, , drop = FALSE]
  finalized <- SplitAlignerR:::finalize_paired_cells(
    fixed$state, fixed$primitive, fixed$fused,
    free$state, free$primitive, free$fused
  )

  expected_pre <- rep("NA", nrow(grid))
  expected_pre[free$state == "mapped" & is.finite(free$primitive)] <- "1"
  expected_pre[free$state == "NA_fuse" & is.finite(free$fused)] <- "NA_fuse"
  expected_final <- expected_pre
  expected_final[free$state == "NA_struct"] <- "NA_struct"
  expected_final[
    free$state == "NA_topo" & fixed$state == "mapped" &
      is.finite(fixed$primitive)
  ] <- "NA_topo"

  expect_identical(finalized$free_pre_promotion_token, expected_pre)
  expect_identical(finalized$final_matrix_token, expected_final)
  expect_identical(
    finalized$summary_class,
    SplitAlignerR:::summary_class_from_final_token(expected_final)
  )
})

test_that("canonical paired finalizer rejects unknown or padded states", {
  call_finalizer <- function(fixed_state = "mapped", free_state = "mapped",
                             fixed_numeric = 1, free_numeric = 1) {
    SplitAlignerR:::finalize_paired_cells(
      fixed_state, fixed_numeric, NA_real_,
      free_state, free_numeric, NA_real_
    )
  }
  expect_error(call_finalizer("NA_other"), "input-quality error")
  expect_error(call_finalizer(free_state = "NA_topoo"), "input-quality error")
  expect_error(call_finalizer(" mapped"), "unpadded")
  expect_error(call_finalizer(free_state = "NA_struct "), "unpadded")
  expect_error(call_finalizer(NA_character_), "Actual R missing")
  expect_error(call_finalizer(fixed_numeric = Inf), "finite values")
  expect_error(
    SplitAlignerR:::finalize_paired_cells(
      "NA_struct", 1, NA_real_, "NA_struct", NA_real_, NA_real_
    ),
    "layers are inconsistent"
  )
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

  structural <- subset(
    paired$paired_ledger, free_primitive_state == "NA_struct"
  )
  expect_gt(nrow(structural), 0L)
  expect_true(all(structural$free_pre_promotion_token == "NA"))
  expect_true(all(structural$final_matrix_token == "NA_struct"))
  expect_true(all(structural$summary_class == "NA_struct"))
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

  unknown <- original
  unknown["g", "B1"] <- "NA_other"
  expect_error(
    SplitAlignerR:::validate_finalized_token_matrix(unknown),
    "invalid token"
  )

  padded <- original
  padded["g", "B1"] <- " NA"
  expect_error(
    SplitAlignerR:::validate_finalized_token_matrix(padded),
    "unpadded"
  )
})

test_that("production paired outputs equal the canonical finalizer", {
  specifications <- list(
    list(
      species = "((A:1,B:1):1,(C:1,D:1):1);",
      fixed = "((A:1,B:1):1,(C:1,D:1):1);",
      free = "((A:1,C:1):1,(B:1,D:1):1);"
    ),
    list(
      species = "((A:1,B:1):1,(C:1,D:1):1);",
      fixed = "((A:1,B:1),(C:1,D:1));",
      free = "((A:1,C:1):1,(B:1,D:1):1);"
    ),
    list(
      species = "((A:1,B:1):1,(C:1,D:1):1);",
      fixed = "((A:1,B:1):1,(C:1,D:1):1);",
      free = "((A:NaN,B:1):1,(C:1,D:1):1);"
    ),
    list(
      species = "((A:1,B:2):3,(C:4,D:5):6);",
      fixed = "(A:4,B:5);",
      free = "(A:4,B:5);"
    ),
    list(
      species = paste0(
        "(((A:1,B:1):1,C:1):1,", "((D:1,E:1):1,F:1):1);"
      ),
      fixed = "((A:1,B:1):1,(D:1,E:1):1);",
      free = "((A:1,D:1):1,(B:1,E:1):1);"
    )
  )

  for (specification in specifications) {
    fixed <- align_branches(
      specification$species, c(g = specification$fixed), mode = "fixed"
    )
    free <- align_branches(
      specification$species, c(g = specification$free), mode = "free"
    )
    paired <- pair_alignment_results(fixed, free)
    coordinates <- colnames(fixed$state_matrix)
    genes <- rownames(fixed$state_matrix)
    cell_gene <- rep(genes, each = length(coordinates))
    fixed_composite <- as.character(fixed$state_ledger$composite_id)
    free_composite <- as.character(free$state_ledger$composite_id)
    fixed_fused <- SplitAlignerR:::composite_evidence_vectors(
      fixed, cell_gene, fixed_composite
    )$value
    free_fused <- SplitAlignerR:::composite_evidence_vectors(
      free, cell_gene, free_composite
    )$value
    canonical <- SplitAlignerR:::finalize_paired_cells(
      as.vector(t(fixed$state_matrix)),
      as.vector(t(fixed$numeric_matrix[, coordinates, drop = FALSE])),
      fixed_fused,
      as.vector(t(free$state_matrix)),
      as.vector(t(free$numeric_matrix[, coordinates, drop = FALSE])),
      free_fused
    )

    expect_identical(
      as.vector(t(paired$fixed_final_matrix)),
      canonical$fixed_output_token
    )
    expect_identical(
      as.vector(t(paired$free_pre_promotion_matrix)),
      canonical$free_pre_promotion_token
    )
    expect_identical(
      as.vector(t(paired$final_matrix)), canonical$final_matrix_token
    )
    expect_identical(
      paired$paired_ledger$summary_class, canonical$summary_class
    )
    expect_false("legacy_gate_failed" %in% names(paired$paired_ledger))
  }
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
