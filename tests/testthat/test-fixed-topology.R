# S4 expected values below are independent of the new graph implementation.
# Unrooted truth comes from the packaged frozen Catnip10 benchmark. Rooted
# local truth is transcribed from the companion benchmark's frozen tables.
# Historical rooted-global helpers below retain the former MRCA convention:
# N_12 is absent from step 1 onward and N_17 from step 6 onward. These are
# differences from the stem-retaining oracle. These helpers are explicitly
# historical: the public S4 entry now preserves S3 reference identity.

fixed_sort_members <- function(x) x[order(as.integer(sub("^B", "", x)))]
fixed_group_id <- function(x) paste0("F[", paste(fixed_sort_members(x), collapse = "|"), "]")

fixed_catnip_rooted_species <- paste0(
  "(t10:0.5603327462,((t1:0.9888917289,(t8:0.0824375581,",
  "((t7:0.9057381309,t4:0.4469696281)N_16:0.3902034671,",
  "t9:0.83600426)N_15:0.5142117843)N_14:0.9466682326)",
  "N_13:0.1387101677,((t5:0.3881082828,t2:0.6851697294)",
  "N_18:0.8110551413,(t3:0.8329160803,t6:0.007334146881)",
  "N_19:0.003948338795)N_17:0.7375956178)N_12:0.9040313873)N_11;"
)

fixed_rooted_crosswalk <- c(
  t10 = "B1", t1 = "B2", t8 = "B3", t7 = "B4", t4 = "B5", t9 = "B6",
  t5 = "B7", t2 = "B8", t3 = "B9", t6 = "B10", N_16 = "B11",
  N_15 = "B12", N_14 = "B13", N_13 = "B14", N_18 = "B15",
  N_19 = "B16", N_17 = "B17", N_12 = "B18"
)

fixed_catnip_data <- function() {
  env <- new.env(parent = emptyenv())
  utils::data("catnip10_oracle", package = "SplitAlignerR", envir = env)
  env$catnip10_oracle
}

fixed_catnip_trees <- function(regime, semantics) {
  data <- fixed_catnip_data()
  species <- if (semantics == "rooted") fixed_catnip_rooted_species else data$species_tree
  phy <- ape::read.tree(text = species)
  deletion <- data[[regime]]$deletion_order
  genes <- lapply(0:length(deletion), function(step) {
    if (step == 0L) phy else ape::drop.tip(phy, deletion[seq_len(step)])
  })
  names(genes) <- paste0("main_step", 0:length(deletion))
  list(species = species, genes = genes)
}

# These helpers exercise the explicitly historical 9007--9009 MRCA contract.
# They are not the public S4 entry and must not define new reference truth.
fixed_historical_mrca <- function(species_tree, gene_trees, tree_semantics = "unrooted",
                                  fusion_view = "whole") {
  species <- as_species_newick(species_tree)
  genes <- as_gene_newicks(gene_trees)
  reference <- .s4_reference(cpp_s4_parse_tree(species$text, TRUE), tree_semantics)
  provider <- function(i) .s4_align_gene(reference,
    cpp_s4_parse_tree(genes$newicks[[i]], FALSE), genes$ids[[i]])
  .assemble_reference_components(reference, provider, genes$ids, fusion_view)
}

# Join by explicit observation IDs only within each gene. This test helper
# makes a component's value inspectable without recreating a public alias.
fixed_component_measurements <- function(result) {
  components <- result$reference_components
  links <- result$component_observations
  observations <- result$observation_ledger
  keys <- function(gene, id) paste(gene, id, sep = "\r")
  link <- match(keys(components$gene_id, components$coordinate_id),
                keys(links$gene_id, links$coordinate_id))
  obs <- match(keys(components$gene_id, links$observation_id[link]),
               keys(observations$gene_id, observations$observation_id))
  components$numeric_value <- observations$numeric_value[obs]
  components$numeric_status <- observations$numeric_status[obs]
  components
}

fixed_check_component_partition <- function(result) {
  for (gene in rownames(result$reference_state_matrix)) {
    components <- subset(result$reference_components, gene_id == gene)
    members <- unlist(components$primitive_members, use.names = FALSE)
    expect_false(anyDuplicated(members) > 0L)
    surviving <- colnames(result$reference_state_matrix)[result$reference_state_matrix[gene, ] != "NA_struct"]
    expect_setequal(members, surviving)
    for (j in seq_len(nrow(components))) {
      expected <- if (length(components$primitive_members[[j]]) == 1L) "observed" else "NA_fuse"
      expect_true(all(result$reference_state_matrix[gene, components$primitive_members[[j]]] == expected))
    }
  }
  for (edges in result$observation_ledger$input_edge_ids) {
    expect_true(length(edges) >= 1L)
    expect_false(anyDuplicated(edges) > 0L)
  }
}

test_that("legacy S4 arguments migrate explicitly without changing positional meaning", {
  species <- "((A,B),C,D);"
  genes <- c(full = "((A:1,B:2):3,C:4,D:5);")
  current <- align_fixed_topology(species, genes, fusion_view = "direct",
    reference_semantics = "unrooted", gene_semantics = "unrooted")
  expect_warning(legacy <- align_fixed_topology(species, genes, NULL, "unrooted", "direct"),
                 "deprecat")
  expect_identical(legacy$reference_state_matrix, current$reference_state_matrix)
  expect_identical(legacy$numeric_matrix, current$numeric_matrix)
  expect_error(align_fixed_topology(species, genes, tree_semantics = "rooted"),
               "migrat|reference_semantics")
  expect_error(align_fixed_topology(species, genes, tree_semantics = "unrooted",
                                   reference_semantics = "unrooted"),
               "tree_semantics|mix|combin")
  expect_error(align_fixed_topology(species, genes, tree_semantics = "unrooted",
                                   gene_semantics = "unrooted"),
               "tree_semantics|mix|combin")
  expect_false(any(c("state_matrix", "component_ledger") %in% names(current)))
})

test_that("S4 independently reproduces all frozen unrooted Catnip10 cells", {
  data <- fixed_catnip_data()
  crosswalk <- with(subset(data$branch_map, splitaligner_branch != "-"),
                    stats::setNames(splitaligner_branch, benchmark_unrooted_branch))
  for (regime in c("global", "local")) {
    input <- fixed_catnip_trees(regime, "unrooted")
    result <- align_fixed_topology(input$species, input$genes, fusion_view = "direct")
    expect_s3_class(result, "splitaligner_fixed_result")
    expect_false(inherits(result, "splitaligner_result"))
    expected <- data[[regime]]$status_long
    for (i in seq_len(nrow(expected))) {
      status <- expected$status[i]
      expect_identical(unname(result$reference_state_matrix[expected$gene_id[i], crosswalk[[expected$branch_id[i]]]]), status)
    }
    fused <- data[[regime]]$fusion_groups
    expected_ids <- character(nrow(fused))
    for (i in seq_len(nrow(fused))) {
      members <- unname(crosswalk[strsplit(fused$benchmark_unrooted_members[i], "|", fixed = TRUE)[[1L]]])
      expected_ids[i] <- fixed_group_id(members)
      measurements <- fixed_component_measurements(result)
      actual <- measurements[measurements$gene_id == fused$gene_id[i] &
          measurements$coordinate_id == expected_ids[i], , drop = FALSE]
      expect_equal(nrow(actual), 1L)
      expect_identical(actual$primitive_members[[1L]], fixed_sort_members(members))
      expect_equal(actual$numeric_value, as.numeric(fused$expected_fused_length[i]), tolerance = 1e-8)
    }
    expect_setequal(result$composite_coordinates$coordinate_id, unique(expected_ids))
    expect_identical(dim(result$reference_state_matrix), c(8L, 17L))
    expect_false(any(result$reference_state_matrix == "NA_topo"))
    fixed_check_component_partition(result)
  }
})

test_that("S4 agrees with S2 throughout their unrooted fixed-topology common domain", {
  for (regime in c("global", "local")) {
    input <- fixed_catnip_trees(regime, "unrooted")
    for (view in c("whole", "direct")) {
      graph <- align_fixed_topology(input$species, input$genes, fusion_view = view)
      split <- align_branches(input$species, input$genes, mode = "fixed", fusion_view = view)
      comparison_states <- graph$reference_state_matrix
      comparison_states[comparison_states == "observed"] <- "mapped"
      expect_identical(comparison_states, split$state_matrix)
      expect_setequal(colnames(graph$numeric_matrix), colnames(split$numeric_matrix))
      expect_equal(graph$numeric_matrix[, colnames(split$numeric_matrix), drop = FALSE],
                   split$numeric_matrix, tolerance = 1e-12)
      expect_identical(graph$composite_coordinates$primitive_members,
                       split$composite_coordinates$primitive_members)
    }
  }
})

fixed_check_historical_partition <- function(result) {
  for (gene in rownames(result$state_matrix)) {
    components <- result$component_ledger[result$component_ledger$gene_id == gene, , drop = FALSE]
    members <- unlist(components$primitive_members, use.names = FALSE)
    sources <- unlist(components$source_nodes, use.names = FALSE)
    expect_false(anyDuplicated(members) > 0L)
    expect_false(anyDuplicated(sources) > 0L)
    expect_true(all(sources >= 0L))
    expect_true(all(vapply(components$source_nodes, is.integer, logical(1))))
    surviving <- colnames(result$state_matrix)[result$state_matrix[gene, ] != "NA_struct"]
    expect_setequal(members, surviving)
    expect_true(all(lengths(components$source_nodes) >= 1L))
    for (j in seq_len(nrow(components))) {
      expected <- if (length(components$primitive_members[[j]]) == 1L) "mapped" else "NA_fuse"
      expect_true(all(result$state_matrix[gene, components$primitive_members[[j]]] == expected))
    }
  }
}

test_that("historical MRCA helper keeps distinct rooted edges and removes ancestral stems", {
  species <- "((A:1,B:2):3,(C:4,D:5):6);"
  genes <- c(full = species, left = "(A:10,B:20):999;", across = "(A:7,C:11);")
  rooted <- fixed_historical_mrca(species, genes, tree_semantics = "rooted", fusion_view = "direct")
  expect_identical(colnames(rooted$state_matrix), paste0("B", 1:6))
  expect_identical(unname(rooted$state_matrix["full", ]), rep("mapped", 6L))
  expect_identical(unname(rooted$numeric_matrix["full", paste0("B", 1:6)]), c(1, 2, 4, 5, 3, 6))
  expect_identical(unname(rooted$state_matrix["left", ]), c("mapped", "mapped", rep("NA_struct", 4L)))
  expect_identical(unname(rooted$numeric_matrix["left", c("B1", "B2")]), c(10, 20))
  expect_identical(unname(rooted$state_matrix["across", ]),
                   c("NA_fuse", "NA_struct", "NA_fuse", "NA_struct", "NA_fuse", "NA_fuse"))
  expect_identical(rooted$numeric_matrix["across", "F[B1|B5]"], 7)
  expect_identical(rooted$numeric_matrix["across", "F[B3|B6]"], 11)
  unrooted <- fixed_historical_mrca(species, c(left = "(A:10,B:20):999;"), tree_semantics = "unrooted")
  expect_identical(unname(unrooted$state_matrix["left", c("B1", "B2")]), rep("NA_fuse", 2L))
  expect_identical(unrooted$numeric_matrix["left", "F[B1|B2]"], 30)
  fixed_check_historical_partition(rooted)
  fixed_check_historical_partition(unrooted)
})

test_that("historical MRCA helper preserves its frozen rooted Catnip10 global result", {
  input <- fixed_catnip_trees("global", "rooted")
  result <- fixed_historical_mrca(input$species, input$genes, tree_semantics = "rooted",
                                 fusion_view = "direct")
  # Historical table + declared root-boundary differences only:
  # B18 (N_12) -> NA_struct at steps 1:7;
  # B17 (N_17) -> NA_struct at steps 6:7.
  encoded <- c("MMMMMMMMMMMMMMMMMM", "SMMMMMMMMMMMMMMMMS", "SSMMMMMMMMMMFFMMMS",
               "SSSMMMMMMMMFFFMMMS", "SSSSFMMMMMFFFFMMMS", "SSSSSFMMMMSFFFMMMS",
               "SSSSSSMMMMSSSSMMSS", "SSSSSSSFMMSSSSFMSS")
  decode <- c(M = "mapped", F = "NA_fuse", S = "NA_struct")
  expected <- t(vapply(strsplit(encoded, ""), function(x) unname(decode[x]), character(18L)))
  dimnames(expected) <- list(paste0("main_step", 0:7), paste0("B", 1:18))
  expect_identical(result$state_matrix, expected)
  steps <- c(2L, 3L, 4L, 4L, 5L, 7L)
  members <- list(c("B13", "B14"), c("B12", "B13", "B14"),
                  c("B12", "B13", "B14"), c("B5", "B11"),
                  c("B6", "B12", "B13", "B14"), c("B8", "B15"))
  values <- c(1.0853784, 1.599590185, 1.599590185, 0.8371730952, 2.435594445, 1.496224871)
  observed <- result$component_ledger[lengths(result$component_ledger$primitive_members) > 1L, , drop = FALSE]
  expect_equal(nrow(observed), length(steps))
  for (i in seq_along(steps)) {
    cell <- observed[observed$gene_id == paste0("main_step", steps[i]) &
                       observed$coordinate_id == fixed_group_id(members[[i]]), , drop = FALSE]
    expect_equal(nrow(cell), 1L)
    expect_identical(cell$primitive_members[[1L]], members[[i]])
    expect_equal(cell$numeric_value, values[i], tolerance = 1e-8)
  }
  expect_true(all(result$state_matrix[2:8, "B18"] == "NA_struct"))
  expect_true(all(result$state_matrix[7:8, "B17"] == "NA_struct"))
  fixed_check_historical_partition(result)
})

test_that("historical MRCA helper preserves its frozen rooted Catnip10 local result", {
  input <- fixed_catnip_trees("local", "rooted")
  result <- fixed_historical_mrca(input$species, input$genes, tree_semantics = "rooted",
                                 fusion_view = "direct")
  # Frozen original-axis states, independently transcribed in legacy B order.
  # M = observed, F = NA_fuse, S = NA_struct; no new S4 helper generated these.
  encoded <- c("MMMMMMMMMMMMMMMMMM", "MMSMMMMMMMMFFMMMMM", "MMSSFMMMMMFFFMMMMM",
               "MMSSSFMMMMSFFMMMMM", "MFSSSSMMMMSSSFMMMM", "MFSSSSSFMMSSSFFMMM",
               "MFSSSSSSMMSSSFSFFM", "MFSSSSSSSFSSSFSFFM")
  decode <- c(M = "mapped", F = "NA_fuse", S = "NA_struct")
  expected <- t(vapply(strsplit(encoded, ""), function(x) unname(decode[x]), character(18L)))
  dimnames(expected) <- list(paste0("main_step", 0:7), paste0("B", 1:18))
  expect_identical(result$state_matrix, expected)
  original_lengths <- c(0.5603327462, 0.9888917289, 0.0824375581, 0.9057381309,
                        0.4469696281, 0.83600426, 0.3881082828, 0.6851697294,
                        0.8329160803, 0.007334146881, 0.3902034671, 0.5142117843,
                        0.9466682326, 0.1387101677, 0.8110551413, 0.003948338795,
                        0.7375956178, 0.9040313873)
  for (row in seq_len(nrow(expected))) {
    mapped <- expected[row, ] == "mapped"
    expect_equal(unname(result$numeric_matrix[row, colnames(expected)[mapped]]), original_lengths[mapped], tolerance = 1e-9)
    expect_true(all(is.na(result$numeric_matrix[row, colnames(expected)[!mapped]])))
  }
  steps <- c(1L, 2L, 2L, 3L, 4L, 5L, 5L, 6L, 6L, 7L, 7L)
  members <- list(c("B12", "B13"), c("B12", "B13"), c("B5", "B11"),
                  c("B6", "B12", "B13"), c("B2", "B14"), c("B2", "B14"),
                  c("B8", "B15"), c("B2", "B14"), c("B16", "B17"),
                  c("B2", "B14"), c("B10", "B16", "B17"))
  values <- c(1.460880017, 1.460880017, 0.8371730952, 2.296884277, 1.127601897,
              1.127601897, 1.496224871, 1.127601897, 0.7415439566, 1.127601897, 0.7488781035)
  observed <- result$component_ledger[lengths(result$component_ledger$primitive_members) > 1L, , drop = FALSE]
  expect_equal(nrow(observed), length(steps))
  for (i in seq_along(steps)) {
    id <- fixed_group_id(members[[i]])
    cell <- observed[observed$gene_id == paste0("main_step", steps[i]) & observed$coordinate_id == id, , drop = FALSE]
    expect_equal(nrow(cell), 1L)
    expect_identical(cell$primitive_members[[1L]], members[[i]])
    expect_equal(cell$numeric_value, values[i], tolerance = 1e-8)
  }
  fixed_check_historical_partition(result)
})


test_that("S4 normalizes an unrooted degree-two display root before freezing aliases", {
  species <- "((A:1,B:2):3,(C:4,D:5):6);"
  result <- align_fixed_topology(species, species)
  expect_identical(colnames(result$reference_state_matrix), paste0("B", 1:5))
  expect_identical(result$primitive_coordinates$primitive_aliases[[5L]], c("B5", "B6"))
  expect_identical(result$numeric_matrix[1L, "B5"], 9)
  expect_true(all(result$reference_state_matrix == "observed"))
  observation <- which(vapply(result$observation_ledger$primitive_members,
                              identical, logical(1), "B5"))
  expect_identical(length(observation), 1L)
  expect_identical(length(result$observation_ledger$input_edge_ids[[observation]]), 2L)
})

test_that("two-tip references have one unrooted edge and two rooted edges", {
  genes <- c(complete = "(B:4,A:3);", missing = "(A,B:4);", marker = "(A:NA,B:4);")
  unrooted <- align_fixed_topology("(A,B);", genes)
  rooted <- align_fixed_topology("(A,B);", genes,
    reference_semantics = "rooted", gene_semantics = "reference_rooted")
  expect_identical(dim(unrooted$reference_state_matrix), c(3L, 1L))
  expect_identical(unrooted$primitive_coordinates$primitive_aliases[[1L]], c("B1", "B2"))
  expect_true(all(unrooted$reference_state_matrix == "observed"))
  expect_identical(unname(unrooted$numeric_matrix[, "B1"]), c(7, NA, NA))
  expect_identical(unrooted$observation_ledger$numeric_status[2:3],
                   c("missing_branch_length", "software_failure_marker"))
  expect_identical(dim(rooted$reference_state_matrix), c(3L, 2L))
  expect_true(all(rooted$reference_state_matrix == "observed"))
  expect_identical(unname(rooted$numeric_matrix["complete", ]), c(3, 4))
  expect_identical(unname(rooted$numeric_matrix[, "B2"]), rep(4, 3L))
  expect_error(align_fixed_topology("(A,B);", "A;"), "two|2|terminal|taxa")
})

test_that("child order and equivalent unrooted root placements preserve branch attribution", {
  species <- "((A,B),(C,D),E);"
  genes <- c(original = "((A:1,B:2):3,(C:4,D:5):6,E:7);",
             rotated = "(E:7,(D:5,C:4):6,(B:2,A:1):3);",
             edge_root = "(A:0.4,(B:2,((D:5,C:4):6,E:7):3):0.6);")
  result <- align_fixed_topology(species, genes)
  for (i in 2:3) {
    expect_identical(unname(result$reference_state_matrix[i, ]), unname(result$reference_state_matrix[1L, ]))
    expect_identical(unname(result$numeric_matrix[i, ]), unname(result$numeric_matrix[1L, ]))
  }
  fixed_check_component_partition(result)
})

test_that("phylo tip indices, internal node numbers, edge order and node labels are not identity", {
  species <- "((A,B),(C,D),E);"
  original <- ape::read.tree(text = "((A:1,B:2):3,(C:4,D:5):6,E:7);")
  changed <- original
  n <- length(original$tip.label)
  tip_permutation <- rev(seq_len(n))
  root <- setdiff(original$edge[, 1L], original$edge[, 2L])
  internal <- setdiff(unique(original$edge[, 1L]), root)
  node_map <- seq_len(n + original$Nnode)
  node_map[seq_len(n)] <- tip_permutation
  node_map[internal] <- rev(internal)
  changed$edge <- matrix(node_map[original$edge], ncol = 2L)
  changed$tip.label[tip_permutation] <- original$tip.label
  changed$node.label <- rep("ignored annotation", original$Nnode)
  rows <- rev(seq_len(nrow(changed$edge)))
  changed$edge <- changed$edge[rows, , drop = FALSE]
  changed$edge.length <- changed$edge.length[rows]
  attr(changed, "order") <- NULL
  result <- align_fixed_topology(species, list(original = original, changed = changed))
  expect_identical(unname(result$reference_state_matrix[1L, ]), unname(result$reference_state_matrix[2L, ]))
  expect_identical(unname(result$numeric_matrix[1L, ]), unname(result$numeric_matrix[2L, ]))
})

test_that("topology mismatch skips conflict, loss and extra refinement with reasons", {
  cases <- list(
    list("((A,B),(C,D));", "((A,C),(B,D));", "unrooted"),
    list("((A,B),(C,D));", "(A,B,C,D);", "unrooted"),
    list("(A,B,C,D);", "((A,B),(C,D));", "unrooted"),
    list("((A,B),(C,D));", "(A,(B,(C,D)));", "rooted"),
    list("(A,B,C);", "((A,B),C);", "rooted")
  )
  for (case in cases) {
    result <- align_fixed_topology(case[[1L]], case[[2L]], gene_ids = "bad_gene",
      reference_semantics = case[[3L]],
      gene_semantics = if (case[[3L]] == "rooted") "reference_rooted" else "unrooted")
    expect_identical(result$gene_outcomes$gene_id, "bad_gene")
    expect_identical(result$gene_outcomes$code, "FIXED_TOPOLOGY_MISMATCH")
    expect_true(nzchar(result$gene_outcomes$reason))
    expect_equal(result$metadata$n_input, 1L)
    expect_equal(result$metadata$n_success, 0L)
    expect_equal(result$metadata$n_skipped_topology, 1L)
    expect_identical(nrow(result$numeric_matrix), 0L)
    expect_false(any(result$reference_state_matrix == "NA_topo"))
  }
})

test_that("valid polytomies are retained exactly rather than forced binary", {
  for (semantics in c("rooted", "unrooted")) {
    result <- align_fixed_topology("(A,B,C,D);", "(D:4,C:3,B:2,A:1);",
      reference_semantics = semantics,
      gene_semantics = if (semantics == "rooted") "reference_rooted" else "unrooted")
    expect_true(all(result$reference_state_matrix == "observed"))
    expect_identical(unname(result$numeric_matrix[1L, ]), c(1, 2, 3, 4))
  }
})

test_that("length availability never changes structural identity or component membership", {
  species <- "((A,B),(C,D),E);"
  genes <- c(finite = "((A:0,B:-2):3,(C:4,D:5):6,E:7);",
             missing = "((A,B:-2):3,(C:4,D:5):6,E:7);",
             marker = "((A:NaN,B:-2):3,(C:4,D:5):6,E:7);")
  result <- align_fixed_topology(species, genes)
  expect_identical(result$numeric_matrix["finite", "B1"], 0)
  expect_identical(result$numeric_matrix["finite", "B2"], -2)
  expect_true(all(result$reference_state_matrix == "observed"))
  expect_true(all(is.na(result$numeric_matrix[c("missing", "marker"), "B1"])))
  first <- subset(fixed_component_measurements(result), coordinate_id == "B1")
  expect_identical(first$numeric_status[2:3], c("missing_branch_length", "software_failure_marker"))
  for (gene in names(genes)[-1L]) {
    expect_identical(subset(result$reference_components, gene_id == gene)$primitive_members,
                     subset(result$reference_components, gene_id == "finite")$primitive_members)
  }
  for (token in c("1junk", "1e9999", "1e-9999")) {
    bad <- paste0("((A:", token, ",B:2):3,(C:4,D:5):6,E:7);")
    expect_error(align_fixed_topology(species, bad), "invalid_numeric|out_of_range")
  }
})

test_that("whole-component sums retain provenance and never alter primitive states", {
  species <- "(((((A,B),C),D),E),F,(G,H));"
  # Three numerical constructions of the same B9/B10/B11 shared coordinate:
  # three singleton edges, a two-member edge plus a singleton, one direct edge.
  all_trees <- readLines(test_path("fixtures", "whole-component-genes.nwk"), warn = FALSE)
  genes <- all_trees[c(1L, 2L, 3L, 4L, 5L, 7L, 8L)]
  names(genes) <- sub("\\(.*$", "", genes)
  genes <- stats::setNames(sub("^[^(]+", "", genes), names(genes))
  whole <- align_fixed_topology(species, genes, fusion_view = "whole")
  direct <- align_fixed_topology(species, genes, fusion_view = "direct")
  target <- "F[B9|B10|B11]"
  expect_identical(unname(whole$numeric_matrix[, target]), c(15, 15, 15, NA, NA, NA, 0))
  expect_identical(unname(direct$numeric_matrix[, target]), c(NA, NA, 15, NA, NA, NA, NA))
  expect_identical(whole$reference_state_matrix, direct$reference_state_matrix)
  expect_identical(whole$reference_components, direct$reference_components)
  expect_identical(whole$observation_ledger, direct$observation_ledger)
  expect_identical(whole$composite_coordinates, direct$composite_coordinates)
  fixed_check_component_partition(whole)
})

test_that("S4 does not fall back to the S2 or Fast branch mapper", {
  local_mocked_bindings(
    cpp_align_branches = function(...) stop("Fast mapper must not be called"),
    align_branches = function(...) stop("S2 facade must not be called"),
    .package = "SplitAlignerR"
  )
  result <- align_fixed_topology("((A,B),C,D);", "(A:3,C:4,D:5);")
  expect_identical(result$numeric_matrix[1L, "F[B1|B5]"], 3)
})
