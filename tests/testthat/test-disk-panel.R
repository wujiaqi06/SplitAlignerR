test_that("disk panels recover primitive matrices and ordered free groups across batches", {
  folder <- tempfile("panel-test-")
  dir.create(folder)
  on.exit(unlink(folder, recursive = TRUE), add = TRUE)
  ref_path <- file.path(folder, "species.nwk")
  free_path <- file.path(folder, "free.nwk")
  fixed_path <- file.path(folder, "fixed.nwk")
  out <- file.path(folder, "panel")

  ref <- "((A,B),C,(D,(E,F)));"
  free_trees <- c(complete = ref, recovered = "((A,B):0.31,D,(E,F):0.17);",
                  absent = "((A,D),B,(E,F):0.23);", star = "(A,B,D,E,F);",
                  two_groups = "((A,D),(B,E));")
  fixed_trees <- free_trees
  fixed_trees[c("absent", "star")] <- free_trees[["recovered"]]
  writeLines(ref, ref_path)
  writeLines(paste0(names(free_trees), free_trees), free_path)
  writeLines(paste0(names(fixed_trees), fixed_trees), fixed_path)
  align_panel_to_disk(ref_path, free_path, out, "paired", fixed_file = fixed_path,
                      batch_size = 2L)

  free <- align_branches(ref, free_trees, "free")
  fixed <- align_branches(ref, fixed_trees, "fixed")
  paired <- pair_alignment_results(fixed, free)
  axis <- colnames(free$state_matrix)
  matrices <- list(free_state = free$state_matrix, free_length = free$numeric_matrix,
                   fixed_state = fixed$state_matrix, fixed_length = fixed$numeric_matrix,
                   paired_free = paired$final_matrix, paired_fixed = paired$fixed_final_matrix)
  ids <- c("two_groups", "recovered", "absent", "complete")
  branches <- axis[c(length(axis), 1L, 3L)]
  for (component in names(matrices)) {
    expect_identical(read_panel_matrix(out, component, ids, branches),
                     matrices[[component]][ids, branches, drop = FALSE])
  }
  expect_identical(read_panel_matrix(out, "free_state", 3L),
                   free$state_matrix[3L, , drop = FALSE])
  expect_error(read_panel_matrix(out, "free_length"))
  expect_error(read_panel_matrix(out, "free_length", "unknown_gene"))
  expect_error(read_panel_matrix(out, "free_length", "absent", "unknown_branch"))

  observed <- read_panel_groups(out, ids)
  oracle <- free_fusion_groups(free)
  rows <- unlist(lapply(ids, function(id) which(oracle$gene_id == id)),
                 use.names = FALSE)
  expected <- oracle[rows, , drop = FALSE]
  rownames(expected) <- NULL
  rownames(observed) <- NULL
  expect_identical(observed, expected)
  expect_true("NA_fuse_topo" %in% observed$graph_class)
  expect_identical(read_panel_groups(out, "complete"), oracle[FALSE, , drop = FALSE])

  fixed_groups <- read_panel_groups(out, ids, role = "fixed")
  fixed_evidence <- fixed$composite_ledger
  definitions <- fixed$composite_coordinates
  fixed_evidence$primitive_members <- definitions$primitive_members[
    match(fixed_evidence$composite_id, definitions$coordinate_id)
  ]
  fixed_rows <- unlist(lapply(ids, function(id) which(fixed_evidence$gene_id == id)),
                       use.names = FALSE)
  expected_fixed <- fixed_evidence[fixed_rows, , drop = FALSE]
  rownames(expected_fixed) <- NULL
  rownames(fixed_groups) <- NULL
  expect_identical(fixed_groups, expected_fixed)
  expect_false("graph_class" %in% names(fixed_groups))

  # The B5/B8 group first occurs in the last shard and has no branch length.
  later <- "F[B5|B8]"
  earlier <- "F[B7|B9]"
  catalog <- panel_fusion_patterns(out)
  expect_setequal(catalog$coordinate_id, c(later, earlier))
  expect_identical(catalog$primitive_members[[match(later, catalog$coordinate_id)]],
                   c("B5", "B8"))
  rows <- c("absent", "complete", "two_groups", "recovered")
  cols <- c(earlier, later)
  expected_status <- matrix(
    c("unrecovered", NA, "unrecovered", "recovered_numeric",
      NA, NA, "recovered_numeric_unavailable", NA),
    nrow = 4L, dimnames = list(rows, cols)
  )
  expect_identical(read_panel_fusions(out, rows, cols, field = "recovery_status"),
                   expected_status)
  expect_identical(read_panel_fusions(out, rows, cols, field = "numeric_value"),
                   free$numeric_matrix[rows, cols, drop = FALSE])
  expect_identical(read_panel_fusions(out, rows, cols, role = "fixed"),
                   fixed$numeric_matrix[rows, cols, drop = FALSE])

  previous <- options(SplitAlignerR.max_panel_cells = 2L)
  on.exit(options(previous), add = TRUE)
  expect_error(read_panel_matrix(out, "paired_free", ids, branches), "fewer")
  expect_identical(read_panel_matrix(out, "paired_free", ids[1L], branches[1:2]),
                   paired$final_matrix[ids[1L], branches[1:2], drop = FALSE])
  options(previous)

  # An unavailable, unrelated shard should not prevent single-gene lookups.
  info <- readRDS(file.path(out, "manifest.rds"))
  unrelated <- file.path(out, info$shards$file[2L])
  expect_true(file.rename(unrelated, paste0(unrelated, ".off")))
  expect_identical(read_panel_matrix(out, "paired_free", "two_groups"),
                   paired$final_matrix["two_groups", , drop = FALSE])
  expect_identical(read_panel_groups(out, "recovered")$gene_id, "recovered")
  expect_true(file.rename(paste0(unrelated, ".off"), unrelated))

  # The altered shard is still a valid RDS file with the correct matrix axes.
  first <- file.path(out, info$shards$file[1L])
  changed <- readRDS(first)
  changed$free_length["complete", 1L] <- 17
  saveRDS(changed, first)
  expect_identical(readRDS(first)$free_length["complete", 1L], 17)
  expect_error(read_panel_matrix(out, "free_length", "complete"), "SHA-256")
})

test_that("a disk panel fails safely on inconsistent paired gene IDs", {
  folder <- tempfile("panel-failure-")
  dir.create(folder)
  on.exit(unlink(folder, recursive = TRUE), add = TRUE)
  ref_path <- file.path(folder, "reference")
  free_path <- file.path(folder, "free")
  fixed_path <- file.path(folder, "fixed")
  out <- file.path(folder, "out")
  ref <- "(A,B,C);"
  writeLines(ref, ref_path)
  writeLines(paste0(c("first", "second"), ref), free_path)
  writeLines(paste0(c("first", "different"), ref), fixed_path)
  expect_error(align_panel_to_disk(ref_path, free_path, out, "paired",
                                   fixed_file = fixed_path, batch_size = 1L))
  expect_false(file.exists(file.path(out, "manifest.rds")))

  existing <- file.path(folder, "existing")
  dir.create(existing)
  sentinel <- file.path(existing, "my-existing-data")
  writeLines("untouched", sentinel)
  expect_error(align_panel_to_disk(ref_path, free_path, existing))
  expect_identical(readLines(sentinel), "untouched")
  expect_false(file.exists(file.path(existing, "manifest.rds")))
})

test_that("single-role panels can have no fusion patterns", {
  folder <- tempfile("panel-one-role-")
  dir.create(folder)
  on.exit(unlink(folder, recursive = TRUE), add = TRUE)
  ref_path <- file.path(folder, "species")
  trees_path <- file.path(folder, "trees")
  ref <- "(A,B,C);"
  tree <- "(A:1,B:2,C:3);"
  writeLines(ref, ref_path)
  writeLines(c("# a small named panel", "", paste0("g", tree)), trees_path)

  for (role in c("free", "fixed")) {
    out <- file.path(folder, role)
    align_panel_to_disk(ref_path, trees_path, out, mode = role)
    alignment <- align_branches(ref, c(g = tree), mode = role)
    expect_identical(read_panel_matrix(out, paste0(role, "_length"), "g"),
                     alignment$numeric_matrix)
    patterns <- panel_fusion_patterns(out)
    expect_identical(patterns$coordinate_id, character())
    expect_identical(patterns$primitive_members, I(list()))
    expect_equal(nrow(patterns), 0L)
    expect_equal(nrow(read_panel_groups(out, "g", role = role)), 0L)
  }
})


test_that("empty fusion catalogs keep their column types", {
  expected <- data.frame(coordinate_id = character(),
                         primitive_members = I(list()),
                         stringsAsFactors = FALSE)
  expect_identical(panel_finish_patterns(list(), c("B1", "B2")), expected)
  expect_identical(panel_finish_patterns(list(list(expected)), c("B1", "B2")),
                   expected)
})
