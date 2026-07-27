with_test_session_options <- function(values, code) {
  old <- options(values)
  on.exit(options(old), add = TRUE)
  force(code)
}

session_option_settings <- expand.grid(
  outdec = c(".", ","),
  scipen = c(-999L, 0L, 999L),
  stringsAsFactors = FALSE
)

session_option_numeric_values <- c(
  0, -0, 1.5, -2.25, 1.2e-8, 1e100
)

expect_canonical_numeric_tokens <- function(tokens) {
  expect_length(tokens, length(session_option_numeric_values))
  expect_identical(tokens[seq_len(4L)], c("0", "-0", "1.5", "-2.25"))
  expect_match(tokens[[5L]], "^1\\.2[eE]-0*8$")
  expect_match(
    tokens[[6L]],
    "^[0-9]+(?:\\.[0-9]+)?[eE]\\+?0*100$",
    perl = TRUE
  )
  expect_false(any(grepl(",", tokens, fixed = TRUE)))
  checked <- validate_branch_length_tokens(tokens)
  expect_true(all(checked$accepted))
  expect_equal(
    checked$value,
    session_option_numeric_values,
    tolerance = 0
  )
}

session_option_public_snapshot <- function(outdec, scipen) {
  with_test_session_options(
    list(OutDec = outdec, scipen = scipen),
    {
      species <- ape::read.tree(text = "((A,B),(C,D));")
      gene <- ape::read.tree(
        text = "((A:1.5,B:2):3,(C:4,D:5):6);"
      )
      multi <- structure(
        list(g1 = gene, g2 = gene),
        class = "multiPhylo"
      )
      gene_list <- unclass(multi)

      fixed <- align_branches(
        species, gene, mode = "fixed", gene_ids = "g"
      )
      free <- align_branches(
        species, gene, mode = "free", gene_ids = "g"
      )
      paired <- pair_alignment_results(fixed, free)

      list(
        fixed = fixed,
        free = free,
        paired = paired,
        multi = align_branches(species, multi, mode = "free"),
        phylo_list = align_branches(species, gene_list, mode = "free"),
        oracle_global = recompute_catnip10_oracle("global"),
        oracle_local = recompute_catnip10_oracle("local")
      )
    }
  )
}

test_that("paired numeric serialization is canonical under session options", {
  original <- options(c("OutDec", "scipen"))
  serialized <- vector("list", nrow(session_option_settings))

  for (i in seq_len(nrow(session_option_settings))) {
    setting <- session_option_settings[i, , drop = FALSE]
    finalized <- with_test_session_options(
      list(OutDec = setting$outdec, scipen = setting$scipen),
      finalize_paired_cells(
        fixed_state = rep("mapped", length(session_option_numeric_values)),
        fixed_primitive_numeric = session_option_numeric_values,
        fixed_fused_numeric = rep(
          NA_real_, length(session_option_numeric_values)
        ),
        free_state = rep("mapped", length(session_option_numeric_values)),
        free_primitive_numeric = session_option_numeric_values,
        free_fused_numeric = rep(
          NA_real_, length(session_option_numeric_values)
        )
      )
    )

    serialized[[i]] <- finalized[c(
      "fixed_output_token", "free_pre_promotion_token",
      "final_matrix_token"
    )]
    expect_canonical_numeric_tokens(finalized$fixed_output_token)
    expect_canonical_numeric_tokens(finalized$free_pre_promotion_token)
    expect_canonical_numeric_tokens(finalized$final_matrix_token)
    expect_identical(
      finalized$summary_class,
      rep("numeric", length(session_option_numeric_values))
    )
    expect_no_error(validate_finalized_token_matrix(matrix(
      finalized$fixed_output_token, nrow = 1L
    )))
    expect_no_error(validate_finalized_token_matrix(matrix(
      finalized$free_pre_promotion_token, nrow = 1L
    )))
    expect_no_error(validate_finalized_token_matrix(matrix(
      finalized$final_matrix_token, nrow = 1L
    )))
  }

  reference_index <- which(
    session_option_settings$outdec == "." &
      session_option_settings$scipen == 0L
  )
  for (value in serialized) {
    expect_identical(value, serialized[[reference_index]])
  }

  expect_identical(options(c("OutDec", "scipen")), original)
})

test_that("public paired and phylo paths are session-option invariant", {
  original <- options(c("OutDec", "scipen"))
  snapshots <- lapply(seq_len(nrow(session_option_settings)), function(i) {
    setting <- session_option_settings[i, , drop = FALSE]
    session_option_public_snapshot(setting$outdec, setting$scipen)
  })
  reference_index <- which(
    session_option_settings$outdec == "." &
      session_option_settings$scipen == 0L
  )
  reference <- snapshots[[reference_index]]

  for (snapshot in snapshots) {
    expect_identical(snapshot, reference)
    tokens <- as.vector(snapshot$paired$final_matrix)
    state <- tokens %in% c("NA", "NA_struct", "NA_fuse", "NA_topo")
    expect_false(any(grepl(",", tokens[!state], fixed = TRUE)))
    expect_true("1.5" %in% tokens[!state])
    expect_true(all(
      validate_branch_length_tokens(tokens[!state])$accepted
    ))
  }

  expect_identical(options(c("OutDec", "scipen")), original)
})

test_that("Catnip10 Oracle matches frozen truth under session options", {
  original <- options(c("OutDec", "scipen"))

  for (i in seq_len(nrow(session_option_settings))) {
    setting <- session_option_settings[i, , drop = FALSE]
    rebuilt <- with_test_session_options(
      list(OutDec = setting$outdec, scipen = setting$scipen),
      lapply(c("global", "local"), recompute_catnip10_oracle)
    )
    names(rebuilt) <- c("global", "local")
    for (regime in names(rebuilt)) {
      expect_identical(rebuilt[[regime]]$matrix,
                       catnip10_oracle[[regime]]$matrix)
      expect_identical(rebuilt[[regime]]$status_long,
                       catnip10_oracle[[regime]]$status_long)
      expect_identical(rebuilt[[regime]]$fusion_groups,
                       catnip10_oracle[[regime]]$fusion_groups)
      expect_identical(rebuilt[[regime]]$deletion_order,
                       catnip10_oracle[[regime]]$deletion_order)
    }
  }

  expect_identical(options(c("OutDec", "scipen")), original)
})

test_that("session options are restored when an invariant case errors", {
  original <- options(c("OutDec", "scipen"))
  expect_error(
    with_test_session_options(
      list(OutDec = ",", scipen = -999L),
      stop("sentinel session-option failure", call. = FALSE)
    ),
    "sentinel session-option failure"
  )
  expect_identical(options(c("OutDec", "scipen")), original)
})
