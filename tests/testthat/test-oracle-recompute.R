test_that("pure R graph oracle exactly rebuilds both frozen Catnip10 scenarios", {
  for (regime in c("global", "local")) {
    rebuilt <- recompute_catnip10_oracle(regime)
    frozen <- catnip10_oracle[[regime]]

    expect_identical(rebuilt$matrix, frozen$matrix)
    expect_identical(rebuilt$status_long, frozen$status_long)
    expect_identical(rebuilt$fusion_groups, frozen$fusion_groups)
    expect_identical(rebuilt$deletion_order, frozen$deletion_order)
    expect_identical(nrow(rebuilt$status_long), 136L)
  }
})

test_that("oracle implementation is independent of the production C++ core", {
  oracle_file <- test_path("../../R/oracle.R")
  if (!file.exists(oracle_file)) {
    skip("Oracle source is not available in installed-package tests")
  }
  source_text <- readLines(oracle_file, warn = FALSE)
  executable <- source_text[!grepl("^\\s*#", source_text)]
  expect_false(any(grepl("cpp_", executable, fixed = TRUE)))
  expect_false(any(grepl("projected_split", executable, fixed = TRUE)))
})

test_that("oracle validates its regime argument", {
  expect_error(recompute_catnip10_oracle("nope"))
})

test_that("oracle matches hand-derived local step-one truth", {
  rebuilt <- recompute_catnip10_oracle("local")
  step_one <- subset(rebuilt$fusion_groups, step_id == "1")
  target <- vapply(
    strsplit(step_one$benchmark_unrooted_members, "|", fixed = TRUE),
    setequal, logical(1), y = c("N_13", "N_14")
  )
  expect_identical(sum(target), 1L)
  expect_equal(
    as.numeric(step_one$expected_fused_length[target]),
    1.4608800169,
    tolerance = 1e-9
  )
  state <- subset(rebuilt$matrix, gene_id == "main_step1")
  expect_identical(state[["t8"]], "NA_struct")
  expect_identical(state[["N_13"]], "NA_fuse")
  expect_identical(state[["N_14"]], "NA_fuse")
  expect_false(state[["t6"]] %in% c("NA_struct", "NA_fuse"))
})

oracle_merge_probe_state <- function(lengths) {
  list(
    edges = data.frame(
      parent_label = c("P", "X"),
      child_label = c("X", "C"),
      branch_length = lengths,
      branch_type = c("internal", "terminal"),
      member_ids = I(list("B1", "B2")),
      edge_uid = 1:2,
      stringsAsFactors = FALSE
    ),
    next_edge_uid = 3L,
    tip_labels = "C"
  )
}

test_that("oracle fused lengths use all-or-none finite evidence", {
  merge <- SplitAlignerR:::.oracle_merge_rows
  finite <- merge(oracle_merge_probe_state(c(1.25, 2.5)), 1L, 2L, "P", "C")
  expect_identical(finite$edges$branch_length, 3.75)

  partial <- merge(
    oracle_merge_probe_state(c(1.25, NA_real_)), 1L, 2L, "P", "C"
  )
  expect_true(is.na(partial$edges$branch_length))
  nonfinite <- merge(
    oracle_merge_probe_state(c(1.25, Inf)), 1L, 2L, "P", "C"
  )
  expect_true(is.na(nonfinite$edges$branch_length))
  expect_error(
    merge(
      oracle_merge_probe_state(rep(.Machine$double.xmax, 2L)),
      1L, 2L, "P", "C"
    ),
    "outside the finite numeric range"
  )
})

oracle_trace <- function(tree, deletion_order) {
  frozen <- SplitAlignerR:::.oracle_freeze_tree_identity(tree)
  state <- SplitAlignerR:::.oracle_init_state(
    frozen$identity, frozen$root_label
  )
  axis <- frozen$identity$branch_id
  values <- vector("list", length(deletion_order) + 1L)
  for (step in 0:length(deletion_order)) {
    if (step > 0L) {
      state <- SplitAlignerR:::.oracle_delete_tip(
        state, deletion_order[[step]]
      )
    }
    values[[step + 1L]] <- SplitAlignerR:::.oracle_classify_state(
      state, frozen$identity
    )[axis]
  }
  do.call(rbind, values)
}

test_that("oracle classifications are invariant to consistent tip relabeling", {
  original <- ape::read.tree(text = catnip10_oracle$species_tree)
  old_labels <- original$tip.label
  mapping <- stats::setNames(
    sprintf("z%02d", rev(seq_along(old_labels))), old_labels
  )
  renamed <- original
  renamed$tip.label <- unname(mapping[old_labels])
  deletion <- catnip10_oracle$local$deletion_order
  original_trace <- oracle_trace(original, deletion)
  renamed_trace <- oracle_trace(renamed, unname(mapping[deletion]))
  renamed_axis_for_original <- colnames(original_trace)
  terminal <- renamed_axis_for_original %in% names(mapping)
  renamed_axis_for_original[terminal] <- unname(
    mapping[renamed_axis_for_original[terminal]]
  )
  expect_identical(
    unname(original_trace),
    unname(renamed_trace[, renamed_axis_for_original, drop = FALSE])
  )
})

unicode_oracle_trace <- function() {
  set.seed(5405)
  tree <- ape::rtree(8L)
  tree$tip.label <- c(
    "é", "E", "β", "Ω", "中", "あ", intToUtf8(0x1F9EC), "Å"
  )
  frozen <- SplitAlignerR:::.oracle_freeze_tree_identity(tree)
  state <- SplitAlignerR:::.oracle_init_state(
    frozen$identity, frozen$root_label
  )
  deletion <- c("中", "E", "Å")
  states <- list()
  ledgers <- list()
  for (step in 0:length(deletion)) {
    if (step > 0L) {
      state <- SplitAlignerR:::.oracle_delete_tip(state, deletion[[step]])
    }
    states[[step + 1L]] <- SplitAlignerR:::.oracle_classify_state(
      state, frozen$identity
    )
    ledgers[[step + 1L]] <- SplitAlignerR:::.oracle_fusion_rows(
      state, paste0("unicode_step", step), step
    )
  }
  list(states = states, ledgers = ledgers)
}

test_that("oracle UTF-8 member and ledger ordering is locale-independent", {
  original_locale <- Sys.getlocale("LC_COLLATE")
  on.exit(Sys.setlocale("LC_COLLATE", original_locale), add = TRUE)
  baseline <- unicode_oracle_trace()
  expect_true(nzchar(Sys.setlocale("LC_COLLATE", "C")))
  under_c <- unicode_oracle_trace()
  expect_identical(under_c, baseline)
})

test_that("oracle character ordering sites explicitly use radix ordering", {
  oracle_file <- test_path("../../R/oracle.R")
  if (!file.exists(oracle_file)) {
    skip("Oracle source is not available in installed-package tests")
  }
  source_text <- paste(readLines(oracle_file, warn = FALSE), collapse = "\n")
  required <- c(
    'sort(endpoints, method = "radix")',
    'root_edges$child_label, root_edges$edge_uid, method = "radix"',
    ')), method = "radix")'
  )
  expect_true(all(vapply(
    required, grepl, logical(1), x = source_text, fixed = TRUE
  )))
  expect_identical(
    length(regmatches(source_text, gregexpr(
      'method = "radix"', source_text, fixed = TRUE
    ))[[1L]]),
    6L
  )
})
