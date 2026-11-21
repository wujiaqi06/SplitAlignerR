s4_observation_case <- function(species, gene, semantics = "rooted") {
  reference <- .s4_reference(cpp_s4_parse_tree(species, TRUE), semantics)
  parsed <- cpp_s4_parse_tree(gene, FALSE)
  prepared <- .s4_prepare_observation(reference, parsed, "example_gene")
  list(reference = reference, parsed = parsed, prepared = prepared)
}

s4_observation_match <- function(case, semantics = "unrooted") {
  .s4_match_observation(case$reference, case$prepared, semantics)
}

test_that("the matching view does not change preserved reference truth", {
  x <- s4_observation_case("((A:10,B:20):30,(C:40,D:50):60);",
                          "((A:1,B:2):3,(C:4,D:5):6);")
  before <- serialize(x, NULL)
  observed <- s4_observation_match(x)
  expect_length(observed, 5L)
  expect_identical(observed[[5L]]$primitive_members, c("B5", "B6"))
  expect_identical(observed[[5L]]$reference_component_ids, c("B5", "B6"))
  expect_identical(observed[[5L]]$numeric_value, 9)
  expect_identical(observed[[5L]]$normalization_mode, "input_edge_sum")
  expect_identical(observed[[5L]]$source_lengths, c(3, 6))
  expect_identical(observed[[5L]]$source_status, rep("finite_numeric", 2L))
  rooted <- s4_observation_match(x, "reference_rooted")
  expect_length(rooted, 6L)
  expect_identical(vapply(rooted, `[[`, numeric(1), "numeric_value"),
                   c(1, 2, 4, 5, 3, 6))
  expect_identical(serialize(x, NULL), before)
  expect_identical(s4_observation_match(x), observed)
})

test_that("unrepresented stems stay in reference components without fake observations", {
  x <- s4_observation_case("((A,B),C);", "(A:2,B:5):999;")
  expect_identical(lapply(x$prepared$reference_components, `[[`, "primitive_members"),
                   list("B1", "B2", "B4"))
  observed <- s4_observation_match(x)
  expect_length(observed, 1L)
  expect_identical(observed[[1L]]$primitive_members, c("B1", "B2"))
  expect_identical(observed[[1L]]$numeric_value, 7)
  expect_false((x$parsed$root - 1L) %in% observed[[1L]]$source_nodes)
  error <- tryCatch(s4_observation_match(x, "reference_rooted"), error = identity)
  expect_s3_class(error, "splitaligner_topology_mismatch")
  expect_identical(error$code, "FIXED_TOPOLOGY_MISMATCH")
  expect_identical(error$gene_id, "example_gene")
  # Preparing truth succeeds independently of the later topology mismatch.
  expect_length(x$prepared$reference_components, 3L)
  preserved <- s4_observation_case("((A,B),C);", "((A:2,B:5):7):999;")
  explicit <- s4_observation_match(preserved, "reference_rooted")
  expect_identical(lapply(explicit, `[[`, "primitive_members"), list("B1", "B2", "B4"))
  expect_identical(vapply(explicit, `[[`, numeric(1), "numeric_value"), c(2, 5, 7))
})

test_that("deletion fusion and representation contraction remain separate", {
  x <- s4_observation_case("(((A,X),B),(C,D));", "(A:10,C:3,D:4);")
  expect_identical(lapply(x$prepared$reference_components, `[[`, "primitive_members"),
                   list(c("B1", "B6", "B7"), "B4", "B5", "B8"))
  observed <- s4_observation_match(x)
  expect_identical(observed[[1L]]$primitive_members, c("B1", "B6", "B7", "B8"))
  expect_identical(observed[[1L]]$reference_component_ids, c("F[B1|B6|B7]", "B8"))
  expect_identical(observed[[1L]]$numeric_value, 10)
  expect_identical(observed[[1L]]$normalization_mode, "single_input_edge")
  expect_length(observed, 3L)
})

test_that("multifurcating roots contract only after becoming degree two", {
  full <- s4_observation_case("(A,B,C,D);", "(D:4,C:3,B:2,A:1);")
  observed <- s4_observation_match(full)
  expect_identical(lapply(observed, `[[`, "primitive_members"), as.list(paste0("B", 1:4)))
  expect_identical(vapply(observed, `[[`, numeric(1), "numeric_value"), as.double(1:4))
  two <- s4_observation_case("(A,B,C,D);", "(A:0,B:0);")
  expect_identical(lapply(two$prepared$reference_components, `[[`, "primitive_members"),
                   list("B1", "B2"))
  joint <- s4_observation_match(two)
  expect_length(joint, 1L)
  expect_identical(joint[[1L]]$reference_component_ids, c("B1", "B2"))
  expect_identical(joint[[1L]]$numeric_value, 0)
  expect_identical(joint[[1L]]$numeric_status, "finite_numeric")
})

test_that("every raw source keeps its length and status through normalization", {
  for (input in c("(A,B:4);", "(A:NA,B:4);", "(A:0,B:0);")) {
    x <- s4_observation_case("(A,B);", input)
    observation <- s4_observation_match(x)[[1L]]
    sources <- observation$source_nodes + 1L
    expect_identical(observation$source_lengths, x$parsed$lengths[sources])
    expect_identical(observation$source_status, x$parsed$numeric_status[sources])
    expect_identical(observation$normalization_mode, "input_edge_sum")
    if (any(observation$source_status == "software_failure_marker")) {
      expect_identical(observation$numeric_status, "software_failure_marker")
      expect_true(is.na(observation$numeric_value))
    } else if (any(observation$source_status == "missing_branch_length")) {
      expect_identical(observation$numeric_status, "missing_branch_length")
      expect_true(is.na(observation$numeric_value))
    } else {
      expect_identical(observation$numeric_status, "finite_numeric")
      expect_identical(observation$numeric_value, 0)
    }
  }
})

test_that("only complete finite observation sums can cause range errors", {
  # The first contraction would overflow if it summed before reaching the
  # missing edge; the complete observation correctly has no available total.
  missing <- s4_observation_case("(A,B);", "((A:1e308):1e308,B);")
  observed <- s4_observation_match(missing)[[1L]]
  expect_identical(observed$numeric_status, "missing_branch_length")
  expect_true(is.na(observed$numeric_value))
  expect_identical(observed$source_lengths,
                   missing$parsed$lengths[observed$source_nodes + 1L])
  marker <- s4_observation_case("(A,B);", "((A:1e308):1e308,B:NA);")
  expect_identical(s4_observation_match(marker)[[1L]]$numeric_status,
                   "software_failure_marker")
  overflow <- s4_observation_case("(A,B);", "(A:1e308,B:1e308);")
  error <- tryCatch(s4_observation_match(overflow), error = identity)
  expect_s3_class(error, "splitaligner_invalid_tree")
  expect_identical(error$code, "NUMERIC_RANGE_ERROR")
  expect_identical(error$gene_id, "example_gene")
  expect_false(inherits(error, "splitaligner_topology_mismatch"))
  # All forms carry the same finite contributions in different raw orders.
  inputs <- c("((A:1e308):-1e308,B:1e-10);",
              "((B:1e-10):1e308,A:-1e308);",
              "(B:-1e308,(A:1e-10):1e308);")
  sums <- vapply(inputs, function(input)
    s4_observation_match(s4_observation_case("(A,B);", input))[[1L]]$numeric_value,
    numeric(1))
  expect_true(all(is.finite(sums)))
  expect_identical(unname(sums), rep(sums[[1L]], length(sums)))
})

test_that("unrooted display changes preserve membership and values", {
  species <- "((A,B),(C,D),E);"
  inputs <- c("((A:1,B:2):3,(C:4,D:5):6,E:7);",
              "(E:7,(D:5,C:4):6,(B:2,A:1):3);",
              "(A:0.4,(B:2,((D:5,C:4):6,E:7):3):0.6);")
  observations <- lapply(inputs, function(input)
    s4_observation_match(s4_observation_case(species, input, "unrooted")))
  for (observed in observations[-1L]) {
    expect_identical(lapply(observed, `[[`, "primitive_members"),
                     lapply(observations[[1L]], `[[`, "primitive_members"))
    expect_equal(vapply(observed, `[[`, numeric(1), "numeric_value"),
                 vapply(observations[[1L]], `[[`, numeric(1), "numeric_value"))
  }
})

test_that("invalid taxa remain fatal and wrong declared roots give typed mismatches", {
  reference <- .s4_reference(cpp_s4_parse_tree("((A,B),(C,D));", TRUE), "rooted")
  error <- tryCatch(.s4_prepare_observation(reference,
    cpp_s4_parse_tree("(A:1,Z:2);", FALSE), "unknown_gene"), error = identity)
  expect_s3_class(error, "splitaligner_invalid_tree")
  expect_identical(error$code, "UNKNOWN_TAXON")
  expect_identical(error$gene_id, "unknown_gene")
  x <- s4_observation_case("((A,B),(C,D));", "(A:1,(B:2,(C:3,D:4):5):6);")
  expect_length(s4_observation_match(x), 5L)
  error <- tryCatch(s4_observation_match(x, "reference_rooted"), error = identity)
  expect_s3_class(error, "splitaligner_topology_mismatch")
  expect_identical(error$code, "FIXED_TOPOLOGY_MISMATCH")
  unrooted <- s4_observation_case("(A,B,C);", "(A:1,B:2,C:3);", "unrooted")
  expect_error(s4_observation_match(unrooted, "reference_rooted"),
               "require a rooted reference")
})

test_that("allowing retained stems does not relax the split reference parser", {
  parsed <- cpp_s4_parse_tree("((A:2,B:5):7);", FALSE)
  expect_equal(sum(parsed$parent == parsed$root), 1L)
  expect_error(cpp_validate_species_tree("((A:2,B:5):7);"),
               "an internal node must contain at least two children")
})

test_that("original references reject unary nodes while gene stems remain valid", {
  for (species in c("((A:1,B:2):3);", "((A:1):2,B:3);")) {
    for (semantics in c("rooted", "unrooted")) {
      expect_error(reference_truth(species, c("A", "B"),
                                   tree_semantics = semantics),
                   "original reference tree must have at least two children")
      expect_error(align_fixed_topology(species, "(A:2,B:5);",
                                        reference_semantics = semantics),
                   "original reference tree must have at least two children")
    }
  }
  # The guard runs before restriction, so it neither removes a retained stem
  # nor rejects the unary gene root needed to represent that stem explicitly.
  result <- align_fixed_topology("((A,B),C);", "((A:2,B:5):7);",
                                 reference_semantics = "rooted",
                                 gene_semantics = "reference_rooted")
  expect_identical(unname(result$primitive_matrix[1L, c("B1", "B2", "B4")]),
                   c(2, 5, 7))
})
