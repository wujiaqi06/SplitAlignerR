# These literal fixtures are copied from the original frozen benchmark, without
# the historical S4 MRCA-stem changes. SOURCE_MANIFEST.json records their origins.

truth_read_tsv <- function(path, ...) {
  utils::read.delim(path, check.names = FALSE, stringsAsFactors = FALSE,
                   colClasses = "character", ...)
}

truth_rooted_crosswalk <- c(
  t10 = "B1", t1 = "B2", t8 = "B3", t7 = "B4", t4 = "B5", t9 = "B6",
  t5 = "B7", t2 = "B8", t3 = "B9", t6 = "B10", N_16 = "B11",
  N_15 = "B12", N_14 = "B13", N_13 = "B14", N_18 = "B15",
  N_19 = "B16", N_17 = "B17", N_12 = "B18"
)

truth_order_members <- function(ids) ids[order(as.integer(sub("^B", "", ids)))]
truth_group_id <- function(ids) paste0("F[", paste(truth_order_members(ids), collapse = "|"), "]")

truth_fixture <- function(regime, semantics) {
  path <- test_path("fixtures", "reference-truth", paste(regime, semantics, sep = "-"))
  schedule <- truth_read_tsv(file.path(path, "benchmark.schedule.tsv"))
  retained <- strsplit(schedule$retained_tip_labels, ",", fixed = TRUE)
  names(retained) <- paste0("main_step", schedule$step_id)
  mapping <- truth_read_tsv(file.path(path, "branch_label_map.tsv"))
  mapping <- mapping[mapping$splitaligner_branch != "-", ]
  crosswalk <- if (semantics == "rooted") truth_rooted_crosswalk else
    stats::setNames(mapping$splitaligner_branch, mapping$benchmark_unrooted_branch)
  list(species = readLines(file.path(path, "benchmark.species_tree.nwk"), warn = FALSE),
       retained = retained, crosswalk = crosswalk,
       matrix = as.matrix(truth_read_tsv(file.path(path,
         "original_matrix.tsv"), row.names = 1L)),
       groups = truth_read_tsv(file.path(path, "oracle_fusion_groups.tsv")))
}

truth_check_partition <- function(x) {
  for (gene in rownames(x$state_matrix)) {
    components <- x$component_ledger[x$component_ledger$gene_id == gene, , drop = FALSE]
    members <- as.character(unlist(components$primitive_members, use.names = FALSE))
    source <- unlist(components$reference_source_nodes, use.names = FALSE)
    expect_false(anyDuplicated(members) > 0L)
    expect_false(anyDuplicated(source) > 0L)
    expect_setequal(members, colnames(x$state_matrix)[x$state_matrix[gene, ] != "NA_struct"])
    expect_true(all(vapply(components$reference_source_nodes, is.integer, logical(1))))
    expect_true(all(source >= 0L))
    for (i in seq_len(nrow(components))) {
      state <- if (length(components$primitive_members[[i]]) == 1L) "observed" else "NA_fuse"
      expect_true(all(x$state_matrix[gene, components$primitive_members[[i]]] == state))
    }
  }
  expect_false("recovery_status" %in% names(x$component_ledger))
  expect_false("recovery_status" %in% names(x$fusion_ledger))
  expect_false("source_nodes" %in% names(x$component_ledger))
}

test_that("S3 reproduces all 560 original Catnip10 cells and 38 fusion groups", {
  cells <- groups <- 0L
  for (regime in c("global", "local")) for (semantics in c("unrooted", "rooted")) {
    input <- truth_fixture(regime, semantics)
    result <- reference_truth(input$species, input$retained,
                              tree_semantics = semantics, fusion_view = "direct")
    expected <- input$matrix
    states <- matrix(ifelse(expected %in% c("NA_struct", "NA_fuse"), expected, "observed"),
                     nrow(expected), ncol(expected), dimnames = dimnames(expected))
    values <- suppressWarnings(matrix(as.numeric(expected), nrow(expected), ncol(expected),
                                      dimnames = dimnames(expected)))
    actual_state <- result$state_matrix[rownames(expected), unname(input$crosswalk[colnames(expected)]), drop = FALSE]
    actual_value <- result$original_matrix[rownames(expected), unname(input$crosswalk[colnames(expected)]), drop = FALSE]
    dimnames(actual_state) <- dimnames(actual_value) <- dimnames(expected)
    expect_identical(actual_state, states)
    expect_equal(actual_value, values, tolerance = 1e-8)
    expect_false(any(result$state_matrix %in% c("mapped", "NA_topo", "NA_fuse_topo")))
    expect_identical(colnames(result$original_matrix), result$primitive_coordinates$coordinate_id)
    expect_identical(colnames(result$fusion_matrix), result$composite_coordinates$coordinate_id)
    expect_false(inherits(result, "splitaligner_result"))
    expect_false(inherits(result, "splitaligner_fixed_result"))
    observed_groups <- result$component_ledger[lengths(result$component_ledger$primitive_members) > 1L, , drop = FALSE]
    expect_identical(nrow(observed_groups), nrow(input$groups))
    for (i in seq_len(nrow(input$groups))) {
      raw_members <- strsplit(input$groups[[paste0("benchmark_", semantics, "_members")]][i],
                              "|", fixed = TRUE)[[1L]]
      members <- truth_order_members(unname(input$crosswalk[raw_members]))
      id <- truth_group_id(members)
      row <- observed_groups[observed_groups$gene_id == input$groups$gene_id[i] &
                               observed_groups$coordinate_id == id, , drop = FALSE]
      expect_equal(nrow(row), 1L)
      expect_identical(row$primitive_members[[1L]], members)
      expect_equal(row$expected_value, as.numeric(input$groups$expected_fused_length[i]), tolerance = 1e-8)
    }
    truth_check_partition(result)
    cells <- cells + length(expected)
    groups <- groups + nrow(input$groups)
  }
  expect_identical(cells, 560L)
  expect_identical(groups, 38L)
})

test_that("S3 and S4 preserve the same original rooted stem identities", {
  input <- truth_fixture("global", "rooted")
  x <- reference_truth(input$species, input$retained, tree_semantics = "rooted")
  expect_identical(unname(x$state_matrix[paste0("main_step", 1:5), "B18"]), rep("observed", 5L))
  expect_equal(unname(x$original_matrix[paste0("main_step", 1:5), "B18"]), rep(0.9040313873, 5L))
  expect_true(all(x$state_matrix[paste0("main_step", 6:7), c("B17", "B18")] == "NA_fuse"))
  expect_equal(unname(x$fusion_matrix[paste0("main_step", 6:7), "F[B17|B18]"]),
               rep(0.9040313873 + 0.7375956178, 2L))
  species <- "((A:1,B:2):3,(C:4,D:5):6);"
  s3 <- reference_truth(species, c("A", "B"), tree_semantics = "rooted")
  s4 <- align_fixed_topology(species, "(A:1,B:2);", reference_semantics = "rooted")
  expect_identical(unname(s3$state_matrix[1, "B5"]), "observed")
  expect_identical(unname(s3$original_matrix[1, "B5"]), 3)
  expect_identical(s4$reference_state_matrix, s3$state_matrix)
  expect_true(is.na(s4$primitive_matrix[1, "B5"]))
  expect_identical(unname(s4$primitive_observation_matrix[1, "B5"]), "unrepresented")
  expect_identical(s4$metadata$root_policy, "original_root_preserved")
  expect_identical(s3$metadata$root_policy, "original_root_preserved")
})

test_that("zero, one and two retained taxa obey distinct rooted and unrooted boundaries", {
  species <- "((A:1,B:2):3,(C:4,D:5):6);"
  sets <- list(empty = character(), one = "A", two = c("A", "B"), across = c("A", "C"))
  rooted <- reference_truth(species, sets, tree_semantics = "rooted", fusion_view = "direct")
  expect_true(all(rooted$state_matrix["empty", ] == "NA_struct"))
  expect_identical(unname(rooted$state_matrix["one", ]),
                   c("NA_fuse", "NA_struct", "NA_struct", "NA_struct", "NA_fuse", "NA_struct"))
  expect_identical(rooted$fusion_matrix["one", "F[B1|B5]"], 4)
  expect_identical(unname(rooted$state_matrix["two", ]),
                   c("observed", "observed", "NA_struct", "NA_struct", "observed", "NA_struct"))
  expect_identical(rooted$original_matrix["two", "B5"], 3)
  expect_identical(rooted$fusion_matrix["across", "F[B3|B6]"], 10)
  unrooted <- reference_truth(species, sets, tree_semantics = "unrooted", fusion_view = "direct")
  expect_true(all(unrooted$state_matrix[c("empty", "one"), ] == "NA_struct"))
  expect_identical(unrooted$fusion_matrix["two", "F[B1|B2]"], 3)
  expect_identical(unname(unrooted$state_matrix["two", ]),
                   c("NA_fuse", "NA_fuse", "NA_struct", "NA_struct", "NA_struct"))
  truth_check_partition(rooted)
  truth_check_partition(unrooted)
  two_rooted <- reference_truth("(A:1,B:2);", list(full = c("A", "B"), one = "A"), tree_semantics = "rooted")
  expect_identical(unname(two_rooted$state_matrix["one", ]), c("observed", "NA_struct"))
  two_unrooted <- reference_truth("(A:1,B:2);", list(full = c("A", "B"), one = "A"))
  expect_identical(dim(two_unrooted$state_matrix), c(2L, 1L))
  expect_identical(two_unrooted$original_matrix["full", "B1"], 3)
  expect_identical(two_unrooted$primitive_coordinates$primitive_aliases[[1]], c("B1", "B2"))
  expect_identical(unname(two_unrooted$state_matrix["one", ]), "NA_struct")
})

test_that("complete current reference components construct fusion values without partial sums", {
  species <- "(((A:1,B:2):3,C:4):5,(D:6,E:7):8);"
  sets <- list(full = c("A", "B", "C", "D", "E"), smaller = c("A", "C", "D", "E"),
               long = c("A", "D", "E"), deleted = c("B", "D", "E"))
  whole <- reference_truth(species, sets, tree_semantics = "rooted")
  direct <- reference_truth(species, sets, tree_semantics = "rooted", fusion_view = "direct")
  expect_identical(whole$state_matrix, direct$state_matrix)
  expect_identical(whole$original_matrix, direct$original_matrix)
  expect_identical(whole$component_ledger, direct$component_ledger)
  long <- "F[B1|B6|B7]"
  short <- "F[B1|B6]"
  expect_identical(unname(whole$fusion_matrix[c("full", "smaller", "long"), long]), rep(9, 3L))
  expect_true(is.na(whole$fusion_matrix["deleted", long]))
  expect_true(is.na(whole$fusion_matrix["long", short]))
  expect_true(all(is.na(direct$fusion_matrix[c("full", "smaller"), long])))
  expect_identical(direct$fusion_matrix["long", long], 9)
  get_cell <- function(gene, id) whole$fusion_ledger[whole$fusion_ledger$gene_id == gene &
                                                   whole$fusion_ledger$composite_id == id, , drop = FALSE]
  expect_identical(get_cell("long", short)$reference_reason, "partial_component")
  expect_identical(get_cell("deleted", long)$reference_reason, "deleted_member_and_partial_component")
  small <- get_cell("smaller", long)
  expect_identical(small$reference_state, "decomposable")
  expect_identical(small$construction_mode, "selected_reference_component_sum")
  expect_identical(small$components[[1]]$primitive_members, I(list(c("B1", "B6"), "B7")))
  expect_identical(get_cell("long", long)$construction_mode, "reference_path_sum")
  expect_false("recovery_status" %in% names(whole$fusion_ledger))
})

test_that("missing reference lengths stay unavailable and valid zeros remain values", {
  sets <- list(full = c("A", "B", "C", "D", "E"), partial = c("A", "C", "D", "E"))
  missing <- reference_truth("(((A:2,B:1),C:4):5,(D:6,E:7):8);", sets, tree_semantics = "rooted")
  expect_identical(unname(missing$state_matrix["full", "B6"]), "observed")
  expect_true(is.na(missing$original_matrix["full", "B6"]))
  expect_true(is.na(missing$fusion_matrix["partial", "F[B1|B6]"]))
  expect_true(is.na(missing$fusion_matrix["full", "F[B1|B6]"]))
  zero <- reference_truth("(((A:0,B:1):0,C:4):5,(D:6,E:7):8);", sets, tree_semantics = "rooted")
  expect_identical(unname(zero$fusion_matrix[, "F[B1|B6]"]), c(0, 0))
  expect_identical(zero$state_matrix, missing$state_matrix)
  marker <- reference_truth("(A:NaN,B:0);", c("A", "B"), tree_semantics = "rooted")
  expect_identical(unname(marker$state_matrix[1, ]), c("observed", "observed"))
  expect_identical(unname(marker$original_matrix[1, ]), c(NA_real_, 0))
  expect_error(reference_truth("(A:1e999,B:1);", c("A", "B")), "range|Rejected|finite")
})

test_that("S3 checks complete-source availability before summing a contracted path", {
  # The lower finite prefix overflows by itself, but the full reference path
  # contains a missing edge. It is unavailable, not a partial numerical sum.
  missing <- "(((A:1e308,B:0):1e308,C:0),D:0);"
  marker <- "(((A:1e308,B:0):1e308,C:0):NaN,D:0);"
  sets <- list(one = "A", full = c("D", "B", "A", "C"))
  x <- reference_truth(missing, sets, tree_semantics = "rooted")
  expect_identical(unname(x$state_matrix["one", ]),
                   c("NA_fuse", "NA_struct", "NA_struct", "NA_struct", "NA_fuse", "NA_fuse"))
  row <- x$component_ledger[x$component_ledger$gene_id == "one", , drop = FALSE]
  expect_identical(row$primitive_members[[1]], c("B1", "B5", "B6"))
  expect_true(is.na(row$expected_value))
  expect_identical(row$expected_status, "missing_branch_length")
  expect_true(is.na(x$fusion_matrix["one", "F[B1|B5|B6]"]))
  y <- reference_truth(marker, "A", tree_semantics = "rooted")
  expect_identical(y$component_ledger$expected_status, "software_failure_marker")
  expect_true(is.na(y$component_ledger$expected_value))
  reordered <- reference_truth(missing, rev(sets), tree_semantics = "rooted")
  expect_identical(x$state_matrix, reordered$state_matrix[rownames(x$state_matrix), , drop = FALSE])
  expect_identical(x$original_matrix, reordered$original_matrix[rownames(x$original_matrix), , drop = FALSE])
  expect_identical(x$fusion_matrix, reordered$fusion_matrix[rownames(x$fusion_matrix), , drop = FALSE])
  all_known <- "(((A:1e308,B:0):1e308,C:0):0,D:0);"
  error <- tryCatch(reference_truth(all_known, list(one = "A"), tree_semantics = "rooted"),
                     error = identity)
  expect_s3_class(error, "splitaligner_invalid_tree")
  expect_identical(error$code, "NUMERIC_RANGE_ERROR")
  expect_identical(error$gene_id, "one")
  # S4 still rejects an overflowing actual gene-edge alias measurement.
  expect_error(align_fixed_topology("(A,B);", "(A:1e308,B:1e308);"), "finite numeric range")
})

# Only the validation helper below uses descendant taxa to compare reference
# presentations. This is an independent test crosswalk, not S3 classification.
truth_reference_keys <- function(newick, semantics) {
  tree <- ape::read.tree(text = newick)
  tips <- length(tree$tip.label)
  children <- split(tree$edge[, 2], tree$edge[, 1])
  root <- setdiff(tree$edge[, 1], tree$edge[, 2])
  post <- function(node) c(unlist(lapply(children[[as.character(node)]], post)), node)
  nodes <- post(root)
  internal <- nodes[nodes > tips & nodes != root]
  order <- c(seq_len(tips), internal)
  descendants <- function(node) if (node <= tips) tree$tip.label[node] else
    unlist(lapply(children[[as.character(node)]], descendants), use.names = FALSE)
  keys <- vapply(order, function(node) {
    left <- paste(sort(descendants(node)), collapse = ",")
    if (semantics == "rooted") return(left)
    right <- paste(sort(setdiff(tree$tip.label, descendants(node))), collapse = ",")
    paste(sort(c(left, right)), collapse = "|")
  }, character(1))
  stats::setNames(keys, paste0("B", seq_along(order)))
}

truth_semantic_records <- function(x, newick, semantics) {
  keys <- truth_reference_keys(newick, semantics)
  ledger <- x$component_ledger
  ledger$semantic_members <- vapply(ledger$primitive_members, function(ids)
    paste(sort(unname(keys[ids])), collapse = ";"), character(1))
  out <- ledger[, c("gene_id", "semantic_members", "expected_value", "expected_status")]
  out <- out[order(out$gene_id, out$semantic_members), , drop = FALSE]
  rownames(out) <- NULL
  out
}

test_that("reference rotations and phylo edge/tip numbering do not change S3 identities", {
  first <- "(((A:1,B:2):3,C:4):5,(D:6,E:7):8);"
  second <- "((E:7,D:6):8,(C:4,(B:2,A:1):3):5);"
  shuffled <- ape::read.tree(text = second)
  permutation <- c(5L, 1L, 3L, 2L, 4L)
  remap <- order(permutation)
  shuffled$tip.label <- shuffled$tip.label[permutation]
  for (column in 1:2) {
    rows <- shuffled$edge[, column] <= 5L
    shuffled$edge[rows, column] <- remap[shuffled$edge[rows, column]]
  }
  row_order <- rev(seq_len(nrow(shuffled$edge)))
  shuffled$edge <- shuffled$edge[row_order, , drop = FALSE]
  shuffled$edge.length <- shuffled$edge.length[row_order]
  attr(shuffled, "order") <- NULL
  sets <- list(full = c("A", "B", "C", "D", "E"), reduced = c("A", "C", "E"), one = "A")
  for (semantics in c("rooted", "unrooted")) {
    a <- reference_truth(first, sets, tree_semantics = semantics)
    b <- reference_truth(second, sets, tree_semantics = semantics)
    c <- reference_truth(shuffled, sets, tree_semantics = semantics)
    expected <- truth_semantic_records(a, a$input$reference_newick, semantics)
    expect_equal(truth_semantic_records(b, b$input$reference_newick, semantics), expected)
    expect_equal(truth_semantic_records(c, c$input$reference_newick, semantics), expected)
  }
})

test_that("S3 validates retained sets and runs without either empirical mapper", {
  species <- "((A:1,B:2):3,C:4);"
  for (bad in list(list(), list(NULL), list(c("A", "A")), list(c("A", NA_character_)),
                   list(c("A", "")), list(c("A", "X")), list(1:2))) {
    expect_error(reference_truth(species, bad))
  }
  expect_error(reference_truth(species, list(a = "A", b = "B"), gene_ids = c("dup", "dup")))
  expect_error(reference_truth(species, list(a = "A"), gene_ids = " leading"))
  expect_error(reference_truth(species, list(a = "A"), gene_trees = "(A,B);"), "unused|argument")
  testthat::local_mocked_bindings(
    align_branches = function(...) stop("S2 mapping must not run"),
    cpp_align_branches = function(...) stop("S2 native mapping must not run"),
    cpp_validate_species_tree = function(...) stop("S2 reference projection must not run"),
    align_fixed_topology = function(...) stop("S4 empirical alignment must not run"),
    .s4_align_gene = function(...) stop("S4 empirical alignment must not run"),
    .package = "SplitAlignerR"
  )
  x <- reference_truth(species, list(none = character(), all = c("A", "B", "C")),
                       tree_semantics = "rooted")
  expect_true(all(x$state_matrix["all", ] == "observed"))
  expect_true(all(x$state_matrix["none", ] == "NA_struct"))
  expect_identical(rownames(reference_truth(species, character())$state_matrix), "gene_000001")
})
