catnip_gene_trees <- function(regime) {
  species <- ape::read.tree(text = catnip10_oracle$species_tree)
  deletion_order <- catnip10_oracle[[regime]]$deletion_order
  trees <- lapply(0:length(deletion_order), function(step) {
    if (step == 0L) {
      species
    } else {
      ape::drop.tip(species, deletion_order[seq_len(step)])
    }
  })
  names(trees) <- paste0("main_step", 0:length(deletion_order))
  trees
}

catnip_branch_crosswalk <- function() {
  map <- subset(catnip10_oracle$branch_map, splitaligner_branch != "-")
  setNames(map$splitaligner_branch, map$benchmark_unrooted_branch)
}

catnip_expected_state_matrix <- function(regime) {
  frozen <- catnip10_oracle[[regime]]$status_long
  crosswalk <- catnip_branch_crosswalk()
  genes <- unique(frozen$gene_id)
  coordinates <- paste0("B", 1:17)
  output <- matrix(
    NA_character_, length(genes), length(coordinates),
    dimnames = list(genes, coordinates)
  )
  for (row in seq_len(nrow(frozen))) {
    state <- if (frozen$status[[row]] == "observed") {
      "mapped"
    } else {
      frozen$status[[row]]
    }
    output[frozen$gene_id[[row]], crosswalk[[frozen$branch_id[[row]]]]] <- state
  }
  output
}

catnip_composite_id <- function(member_text) {
  crosswalk <- catnip_branch_crosswalk()
  members <- unname(crosswalk[strsplit(member_text, "|", fixed = TRUE)[[1L]]])
  members <- members[order(as.integer(sub("B", "", members, fixed = TRUE)))]
  paste0("F[", paste(members, collapse = "|"), "]")
}

test_that("topology state is independent of numeric availability", {
  species <- "((A:1,B:1):1,(C:1,D:1):1);"
  genes <- c(
    concordant = "((A:1,B:1):1,(C:1,D:1):1);",
    discordant = "((A:1,C:1):1,(B:1,D:1):1);",
    marker = "((A:NaN,B:1):1,(C:1,D:1):1);"
  )
  aligned <- align_branches(species, genes)

  expect_s3_class(aligned, "splitaligner_result")
  expect_identical(
    unname(aligned$state_matrix["discordant", ]),
    c("mapped", "mapped", "mapped", "mapped", "NA_topo")
  )
  expect_identical(aligned$state_matrix["marker", "B1"], "mapped")
  expect_true(is.na(aligned$numeric_matrix["marker", "B1"]))
  marker_row <- subset(
    aligned$state_ledger,
    gene_id == "marker" & coordinate_id == "B1"
  )
  expect_false(marker_row$numeric_available)
  expect_identical(marker_row$numeric_status, "software_failure_marker")
  expect_identical(
    subset(
      aligned$diagnostics,
      gene_id == "marker" & code == "SOFTWARE_FAILURE_MARKER"
    )$count,
    1L
  )
})

test_that("gene numeric policy rejects invalid and non-finite-range values", {
  species <- "((A,B),(C,D));"
  expect_error(
    align_branches(species, "((A:1junk,B:1):1,(C:1,D:1):1);"),
    "invalid_numeric"
  )
  expect_error(
    align_branches(species, "((A:1e9999,B:1):1,(C:1,D:1):1);"),
    "out_of_range"
  )

  negative <- align_branches(
    species, "((A:-0.5,B:1):1,(C:1,D:1):1);"
  )
  expect_identical(negative$numeric_matrix[1L, "B1"], -0.5)
  expect_identical(
    subset(negative$diagnostics, code == "NEGATIVE_BRANCH_LENGTH")$count,
    1L
  )
})

test_that("common software failure spellings never change recovered topology", {
  species <- "((A,B),(C,D));"
  markers <- c("NaN", "-nan", "Inf", "-Inf", "NA", "?", ".")
  genes <- setNames(
    paste0("((A:", markers, ",B:1):1,(C:1,D:1):1);"),
    paste0("marker_", seq_along(markers))
  )
  aligned <- align_branches(species, genes)

  expect_true(all(aligned$state_matrix[, "B1"] == "mapped"))
  expect_true(all(is.na(aligned$numeric_matrix[, "B1"])))
  marker_counts <- subset(
    aligned$diagnostics,
    code == "SOFTWARE_FAILURE_MARKER"
  )$count
  expect_identical(marker_counts, rep(1L, length(markers)))
})

test_that("gene tree input conversion is deterministic and bounded", {
  species <- "((A,B),(C,D));"
  path <- tempfile(fileext = ".trees")
  writeLines(c(
    "named((A:1,B:1):1,(C:1,D:1):1);",
    "((A:2,B:2):2,(C:2,D:2):2);"
  ), path)
  from_file <- align_branches(species, path)
  expect_identical(rownames(from_file$state_matrix), c("named", "gene_000002"))

  phy <- ape::read.tree(text = "((A:1,B:1):1,(C:1,D:1):1);")
  one_phy <- align_branches(species, phy)
  expect_identical(rownames(one_phy$state_matrix), "gene_000001")
  multi <- structure(list(first = phy, second = phy), class = "multiPhylo")
  from_multi <- align_branches(species, multi)
  expect_identical(rownames(from_multi$state_matrix), c("first", "second"))

  expect_error(align_branches(species, c(x = ape::write.tree(phy),
                                         x = ape::write.tree(phy))),
               "Duplicate gene identifier")
  expect_error(align_branches(species, "((A,B),(C,X));"),
               "absent from the species tree")
  expect_error(align_branches(species, "((A,A),(C,D));"),
               "duplicate terminal")
  expect_error(align_branches(species, phy, future_option = TRUE),
               "reserved")
})

test_that("explicit gene IDs reject missing, empty, padded, control, and duplicate values", {
  species <- "((A,B),(C,D));"
  tree <- "((A:1,B:1):1,(C:1,D:1):1);"

  expect_error(
    align_branches(species, tree, gene_ids = NA_character_),
    "must not contain missing"
  )
  expect_error(
    align_branches(species, tree, gene_ids = ""),
    "must not contain empty"
  )
  for (id in c(" padded", "padded ", "\u00a0padded", "padded\u3000")) {
    expect_error(
      align_branches(species, tree, gene_ids = id),
      "leading or trailing whitespace"
    )
  }
  for (id in c("gene\tid", "gene\nid", "gene\rid", paste0("gene", intToUtf8(0x80)))) {
    expect_error(
      align_branches(species, tree, gene_ids = id),
      "control characters"
    )
  }
  expect_error(
    align_branches(
      species, c(tree, tree), gene_ids = c("duplicate", "duplicate")
    ),
    "Duplicate gene identifier"
  )
})

test_that("explicit Unicode gene IDs and deterministic automatic IDs remain valid", {
  species <- "((A,B),(C,D));"
  tree <- "((A:1,B:1):1,(C:1,D:1):1);"
  unicode_ids <- c("基因α", paste0("δένδρο", intToUtf8(0x1F9EC)))
  explicit <- align_branches(
    species, c(tree, tree), gene_ids = unicode_ids
  )
  expect_identical(
    enc2utf8(rownames(explicit$state_matrix)),
    enc2utf8(unicode_ids)
  )
  expect_identical(
    enc2utf8(unique(explicit$state_ledger$gene_id)),
    enc2utf8(unicode_ids)
  )
  expect_identical(
    enc2utf8(explicit$gene_provenance$gene_id),
    enc2utf8(unicode_ids)
  )

  automatic <- align_branches(species, c(tree, tree))
  expect_identical(
    rownames(automatic$state_matrix),
    c("gene_000001", "gene_000002")
  )
})

test_that("C++ graph-first states reproduce all 272 Catnip10 cells", {
  for (regime in c("global", "local")) {
    aligned <- align_branches(
      catnip10_oracle$species_tree,
      catnip_gene_trees(regime),
      mode = "fixed"
    )
    expected <- catnip_expected_state_matrix(regime)
    expect_identical(aligned$state_matrix, expected)
    expect_identical(nrow(aligned$state_ledger), 136L)
    expect_false(any(aligned$state_matrix == "NA_topo"))
    expect_identical(
      sum(subset(
        aligned$diagnostics,
        code == "FIXED_TOPOLOGY_MISMATCH"
      )$count),
      0L
    )
  }
})

test_that("C++ composite provenance and values match the Catnip10 Oracle", {
  for (regime in c("global", "local")) {
    aligned <- align_branches(
      catnip10_oracle$species_tree,
      catnip_gene_trees(regime),
      mode = "fixed"
    )
    expected <- catnip10_oracle[[regime]]$fusion_groups
    expected$composite_id <- vapply(
      expected$benchmark_unrooted_members,
      catnip_composite_id,
      character(1)
    )
    expected$numeric_value <- as.numeric(expected$expected_fused_length)
    expected <- expected[c("gene_id", "composite_id", "numeric_value")]
    observed <- aligned$composite_ledger[
      c("gene_id", "composite_id", "numeric_value")
    ]
    expected <- expected[order(expected$gene_id, expected$composite_id), ]
    observed <- observed[order(observed$gene_id, observed$composite_id), ]
    rownames(expected) <- rownames(observed) <- NULL

    expect_identical(observed[c("gene_id", "composite_id")],
                     expected[c("gene_id", "composite_id")])
    expect_equal(observed$numeric_value, expected$numeric_value,
                 tolerance = 1e-9)
    expect_true(all(aligned$composite_ledger$recovery_status ==
                      "recovered_numeric"))
  }
})

test_that("two-tip restriction and multifurcation keep graph semantics", {
  species <- "((A:1,B:2):3,(C:4,D:5):6);"
  two_tip <- align_branches(species, "(A:4,B:5);")
  expect_identical(
    unname(two_tip$state_matrix[1L, ]),
    c("NA_fuse", "NA_fuse", "NA_struct", "NA_struct", "NA_struct")
  )
  expect_identical(two_tip$composite_coordinates$member_text, "B1|B2")
  expect_identical(two_tip$composite_ledger$numeric_value, 9)

  polytomy <- align_branches(species, "(A:1,B:2,C:3,D:4);")
  expect_identical(
    unname(polytomy$state_matrix[1L, ]),
    c("mapped", "mapped", "mapped", "mapped", "NA_topo")
  )
  expect_identical(
    subset(polytomy$diagnostics, code == "MULTIFURCATING_GENE_NODE")$count,
    1L
  )
})

test_that("partially missing fused length is all-or-none numeric evidence", {
  aligned <- align_branches(
    "(((A:1,B:1):1,C:1):1,D:1);",
    c(g = "((A,C:1):1,D:1);"),
    mode = "free"
  )
  expect_identical(aligned$composite_coordinates$coordinate_id, "F[B1|B5]")
  expect_identical(
    aligned$composite_coordinates$primitive_members[[1L]], c("B1", "B5")
  )
  expect_identical(aligned$composite_ledger$recovery_status,
                   "recovered_numeric_unavailable")
  expect_identical(aligned$composite_ledger$numeric_status,
                   "missing_branch_length")
  expect_false(aligned$composite_ledger$numeric_available)
  expect_true(is.na(aligned$composite_ledger$numeric_value))
  expect_true(is.na(aligned$numeric_matrix["g", "F[B1|B5]"]))
})

test_that("gene labels and annotations are ignored with diagnostics", {
  aligned <- align_branches(
    "((A,B)95[&species=1],(C,D)88);",
    "[&R]((A:1,B:1)99[&support=1]:2,(C:1,D:1)88:3)root:999;"
  )
  counts <- setNames(aligned$diagnostics$count, aligned$diagnostics$code)
  expect_identical(counts[["IGNORED_GENE_ROOT_LENGTH"]], 1L)
  expect_identical(counts[["IGNORED_INTERNAL_LABEL"]], 3L)
  expect_identical(counts[["IGNORED_ANNOTATION_BLOCK"]], 2L)
  expect_true(all(aligned$state_matrix == "mapped"))
})

test_that("alignment output is deterministic", {
  species <- "((A:1,B:2):3,(C:4,D:5):6);"
  genes <- c(
    x = "((A:1,B:2):3,(C:4,D:5):6);",
    y = "((A:2,C:3):4,(B:5,D:6):7);"
  )
  first <- align_branches(species, genes)
  second <- align_branches(species, genes)
  expect_identical(first, second)
})
