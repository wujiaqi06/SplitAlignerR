s4_memory_example <- function(view = "whole") {
  species <- "(((A:1,B:2)u:3,C:4)p:5,(D:6,E:7)q:8)r;"
  genes <- c(full = species,
    smaller = "((A:4,C:4):5,(D:6,E:7):8);",
    long = "(A:9,(D:6,E:7):8);",
    deleted = "(B:10,(D:6,E:7):8);",
    missing = "(((A,B:2):3,C:4):5,(D:6,E:7):8);",
    marker = "(((A:NA,B:2):3,C:4):5,(D:6,E:7):8);",
    zero = "(((A:0,B:2):0,C:4):0,(D:6,E:7):8);")
  align_fixed_topology(species, genes, reference_semantics = "rooted",
                       fusion_view = view)
}

test_that("S4 fusion columns preserve order and complete source records", {
  for (view in c("whole", "direct")) {
    x <- s4_memory_example(view)
    ledger <- x$fusion_ledger
    expect_identical(ledger$gene_id,
      rep(rownames(x$fusion_matrix), times = ncol(x$fusion_matrix)))
    expect_identical(ledger$composite_id,
      rep(colnames(x$fusion_matrix), each = nrow(x$fusion_matrix)))
    expect_identical(ledger$numeric_value, as.vector(x$fusion_matrix))
    expect_identical(ledger$numeric_available, is.finite(ledger$numeric_value))
    expect_true(any(ledger$reference_state == "unavailable"))
    expect_true(any(ledger$observation_status == "unavailable"))

    for (i in seq_len(nrow(ledger))) {
      observations <- x$observation_ledger[
        x$observation_ledger$gene_id == ledger$gene_id[[i]], , drop = FALSE]
      rownames(observations) <- NULL
      coordinate <- match(ledger$composite_id[[i]],
                          x$composite_coordinates$coordinate_id)
      target <- x$composite_coordinates$primitive_members[[coordinate]]
      # Even a partial observation remains in the provenance. A reference
      # target that is unavailable does not proceed to observation selection.
      touched <- if (ledger$reference_state[[i]] == "unavailable") integer() else
        which(vapply(observations$primitive_members,
          function(members) any(members %in% target), logical(1)))
      expect_identical(ledger$sources[[i]], observations[touched, , drop = FALSE])
    }

    # The output remains ordinary serializable R tables, including nested
    # source data.frames and the AsIs list columns expected by callers.
    expect_identical(unserialize(serialize(x, NULL, version = 2)), x)
    expect_identical(unserialize(serialize(x, NULL, version = 3)), x)
  }
})

test_that("S4 scalar evaluation avoids source frames without changing decisions", {
  x <- s4_memory_example()
  axis <- x$primitive_coordinates$coordinate_id
  gene <- "missing"
  refs <- x$reference_components[x$reference_components$gene_id == gene, , drop = FALSE]
  obs <- x$observation_ledger[x$observation_ledger$gene_id == gene, , drop = FALSE]
  rownames(refs) <- rownames(obs) <- NULL
  reference_index <- SplitAlignerR:::.s4_member_index(refs$primitive_members, axis)
  observation_index <- SplitAlignerR:::.s4_member_index(obs$primitive_members, axis)
  targets <- c(as.list(seq_along(axis)),
    lapply(x$composite_coordinates$primitive_members, match, table = axis))
  for (view in c("whole", "direct")) for (target in targets) {
    detailed <- SplitAlignerR:::.s4_observation_cell(target, reference_index,
      observation_index, obs, view)
    scalar <- SplitAlignerR:::.s4_observation_cell(target, reference_index,
      observation_index, obs, view, details = FALSE)
    expect_null(scalar$sources)
    fields <- setdiff(names(detailed), "sources")
    expect_identical(scalar[fields], detailed[fields])
  }
})

test_that("S4 all-skipped assembly preserves typed empty empirical outputs", {
  species <- "((A:1,B:2):3,C:4,(D:5,E:6):7);"
  genes <- c(first = "((A:1,D:2):3,(C:4,E:5):6);",
             second = "((A:2,D:3):4,(C:5,E:6):7);")
  x <- align_fixed_topology(species, genes)
  expect_identical(x$metadata$topology_status, "all_skipped")
  expect_equal(nrow(x$reference_state_matrix), 2L)
  expect_gt(nrow(x$composite_coordinates), 0L)
  expect_equal(nrow(x$fusion_matrix), 0L)
  expect_equal(nrow(x$fusion_ledger), 0L)
  expect_equal(nrow(x$observation_ledger), 0L)
  expect_identical(typeof(x$fusion_ledger$numeric_value), "double")
  expect_identical(typeof(x$fusion_ledger$numeric_available), "logical")
  expect_identical(class(x$fusion_ledger$sources), "AsIs")
  expect_identical(class(x$fusion_ledger$observation_ids), "AsIs")
  expect_identical(names(x$observation_ledger), c("gene_id", "observation_id",
    "relation", "reference_component_ids", "primitive_members", "input_edge_ids",
    "source_lengths", "source_status", "normalization_mode", "numeric_status",
    "numeric_value"))
  expect_identical(unserialize(serialize(x, NULL)), x)
})
