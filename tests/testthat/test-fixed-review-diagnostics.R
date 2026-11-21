s4_review_capture_error <- function(expr) tryCatch(expr, error = identity)

test_that("S4 prepare and match failures name the offending gene and retain their type", {
  species <- "((A,B),(C,D));"
  good <- "((A:1,B:2):3,(C:4,D:5):6);"
  unknown <- "((A:1,B:2):3,(C:4,Z:5):6);"
  overflow <- "((A:1,B:2):1e308,(C:4,D:5):1e308);"
  reference <- .s4_reference(cpp_s4_parse_tree(species, TRUE), "unrooted")
  raw_unknown <- s4_review_capture_error(.s4_prepare_observation(reference,
    cpp_s4_parse_tree(unknown, FALSE), "unknown_gene"))
  error <- s4_review_capture_error(align_fixed_topology(species,
    c(before = good, unknown_gene = unknown, after = good)))
  expect_identical(class(error), class(raw_unknown))
  expect_identical(error$code, "UNKNOWN_TAXON")
  expect_identical(error$gene_id, "unknown_gene")
  expect_match(conditionMessage(error), "Gene tree `unknown_gene`", fixed = TRUE)
  expect_match(conditionMessage(error), conditionMessage(raw_unknown), fixed = TRUE)
  expect_false(inherits(error, "splitaligner_topology_mismatch"))

  prepared <- .s4_prepare_observation(reference,
    cpp_s4_parse_tree(overflow, FALSE), "overflow_gene")
  raw_overflow <- s4_review_capture_error(
    .s4_match_observation(reference, prepared, "unrooted"))
  error <- s4_review_capture_error(align_fixed_topology(species,
    c(before = good, overflow_gene = overflow, after = good)))
  expect_identical(class(error), class(raw_overflow))
  expect_identical(error$code, "NUMERIC_RANGE_ERROR")
  expect_identical(error$gene_id, "overflow_gene")
  expect_match(conditionMessage(error), "Gene tree `overflow_gene`", fixed = TRUE)
  expect_match(conditionMessage(error), conditionMessage(raw_overflow), fixed = TRUE)
  expect_false(inherits(error, "splitaligner_topology_mismatch"))
})

test_that("S4 parser, duplicate-label and invalid-numeric errors retain native classes", {
  species <- "((A,B),(C,D));"
  bad <- c(parse_gene = "((A,B),,C);",
           duplicate_gene = "((A,A),(C,D));",
           numeric_gene = "((A:1junk,B),(C,D));")
  for (id in names(bad)) {
    raw <- s4_review_capture_error(cpp_s4_parse_tree(bad[[id]], FALSE))
    error <- s4_review_capture_error(align_fixed_topology(species,
      stats::setNames(c(species, bad[[id]]), c("good_gene", id))))
    expect_s3_class(error, "error")
    expect_identical(class(error), class(raw))
    expect_identical(error$code, raw$code)
    expect_identical(error$gene_id, id)
    expect_match(conditionMessage(error), paste0("Gene tree `", id, "`"), fixed = TRUE)
    expect_match(conditionMessage(error), conditionMessage(raw), fixed = TRUE)
    expect_false(inherits(error, "splitaligner_topology_mismatch"))
  }
})

test_that("gene context preserves simple and structured error metadata", {
  simple <- simpleError("specific simple failure", call = quote(example_call()))
  typed <- structure(list(message = "specific typed failure", call = quote(typed_call()),
    gene_id = "typed_gene", code = "NUMERIC_RANGE_ERROR", detail = list(source = 7L)),
    class = c("splitaligner_invalid_tree", "error", "condition"))
  for (original in list(simple, typed)) {
    id <- if (is.null(original$gene_id)) "simple_gene" else original$gene_id
    error <- s4_review_capture_error(.s4_with_gene_context(id, stop(original)))
    expect_identical(class(error), class(original))
    expect_identical(error$call, original$call)
    expect_identical(error$code, original$code)
    expect_identical(error$detail, original$detail)
    expect_identical(error$gene_id, id)
    expect_match(conditionMessage(error), paste0("Gene tree `", id, "`"), fixed = TRUE)
    # Repeated decoration must not duplicate the same readable context.
    again <- s4_review_capture_error(.s4_with_gene_context(id, stop(error)))
    expect_identical(again, error)
  }
})

test_that("only typed fixed-topology mismatches remain skippable", {
  species <- "((A,B),(C,D));"
  mismatch <- "((A,C),(B,D));"
  x <- align_fixed_topology(species, c(before = species, mismatch_gene = mismatch,
                                      after = species))
  expect_identical(x$gene_outcomes$outcome, c("success", "skipped", "success"))
  expect_identical(x$gene_outcomes$code[[2L]], "FIXED_TOPOLOGY_MISMATCH")
  expect_match(x$gene_outcomes$reason[[2L]], "mismatch_gene", fixed = TRUE)
  expect_identical(rownames(x$numeric_matrix), c("before", "after"))
  error <- s4_review_capture_error(align_fixed_topology(species,
    c(mismatch_gene = mismatch, invalid_gene = "((A,B),(C,Z));")))
  expect_s3_class(error, "splitaligner_invalid_tree")
  expect_identical(error$gene_id, "invalid_gene")
  expect_identical(error$code, "UNKNOWN_TAXON")
})

test_that("an unrepresented stem reason describes the unrooted view, not input absence", {
  species <- "((A,B),C);"
  genes <- c(without_stem = "(A:2,B:5);", with_stem = "((A:2,B:5):91);")
  x <- align_fixed_topology(species, genes, reference_semantics = "rooted")
  stems <- x$component_observations[x$component_observations$coordinate_id == "B4", ]
  expect_identical(stems$gene_id, names(genes))
  expect_identical(stems$relation, rep("unrepresented", 2L))
  expect_identical(stems$representation_reason,
                   rep("ancestral_stem_outside_unrooted_view", 2L))
  expect_true(all(is.na(stems$observation_id)))
  expect_identical(unname(x$reference_state_matrix[, "B4"]), rep("observed", 2L))
  expect_true(all(is.na(x$primitive_matrix[, "B4"])))
  expect_identical(x$observation_ledger$numeric_value, c(7, 7))
  expect_false("B4" %in% unlist(x$observation_ledger$primitive_members, use.names = FALSE))
  expect_identical(x$input$gene_newicks, genes)
  explicit <- align_fixed_topology(species, genes[["with_stem"]],
    reference_semantics = "rooted", gene_semantics = "reference_rooted")
  expect_identical(unname(explicit$primitive_matrix[, "B4"]), 91)
  expect_identical(explicit$component_observations$representation_reason,
                   rep("represented", 3L))
})
