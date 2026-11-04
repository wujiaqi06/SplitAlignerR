# Frozen scalar algorithm from historical e847dd0, retained only as a test oracle.
fast_adapter_scalar_byte_key <- function(ids) {
  vapply(ids, function(id) {
    paste(as.character(charToRaw(id)), collapse = "")
  }, character(1), USE.NAMES = FALSE)
}

fast_adapter_encoding_samples <- function() {
  utf8 <- rawToChar(as.raw(c(0xc3, 0xa9)))
  Encoding(utf8) <- "UTF-8"
  latin1 <- rawToChar(as.raw(0xe9))
  Encoding(latin1) <- "latin1"
  unknown <- utf8
  Encoding(unknown) <- "unknown"
  bytes <- utf8
  Encoding(bytes) <- "bytes"
  invalid_unknown <- rawToChar(as.raw(c(0xff, 0x28)))
  Encoding(invalid_unknown) <- "unknown"
  invalid_utf8 <- rawToChar(as.raw(c(0xc3, 0x28)))
  Encoding(invalid_utf8) <- "UTF-8"
  c(utf8 = utf8, latin1 = latin1, unknown = unknown, bytes = bytes,
    invalid_unknown = invalid_unknown, invalid_utf8 = invalid_utf8)
}

fast_adapter_result_fixture <- function() {
  ids <- c(paste0("gene_", intToUtf8(0xe9)), "fused")
  align_branches(
    "((A,B),(C,D));",
    c("((A:NaN,B:2):3,(C:4,D:5):6);", "(A:2,B:3);"),
    gene_ids = ids
  )
}

test_that("byte-key deduplication matches the scalar oracle without transcoding", {
  samples <- fast_adapter_encoding_samples()
  cases <- list(
    character(), "", c("", ""), "ordinary", rep("ordinary", 257L),
    c(NA_character_, "NA", NA_character_, "NA"), samples,
    rep(c(samples, "", NA_character_, "NA", "ascii"), 31L)
  )
  for (values in cases) {
    original_encodings <- Encoding(values)
    original_bytes <- lapply(values, charToRaw)
    expect_identical(gene_id_byte_key(values),
                     fast_adapter_scalar_byte_key(values))
    expect_identical(Encoding(values), original_encodings)
    expect_identical(lapply(values, charToRaw), original_bytes)

    names(values) <- rep("ignored_input_name", length(values))
    expect_identical(gene_id_byte_key(values),
                     fast_adapter_scalar_byte_key(values))
    expect_null(names(gene_id_byte_key(values)))
  }
  expect_identical(
    gene_id_byte_key(samples),
    c("c3a9", "e9", "c3a9", "c3a9", "ff28", "c328")
  )
  # Preserve the historical scalar helper's NA spelling, without weakening
  # the separate public-input or matrix-axis missing-value checks.
  expect_identical(gene_id_byte_key(c(NA_character_, "NA")),
                   c("4e41", "4e41"))
})

test_that("byte-key fallback keeps scalar behavior for nonstandard inputs", {
  classed <- structure(rep(fast_adapter_encoding_samples()[1:4], 2L),
                       class = "fast_adapter_ids")
  dimensional <- matrix(c("first", "first", "last", "first"), nrow = 2L,
                        dimnames = list(c("r1", "r2"), c("c1", "c2")))
  cases <- list(NULL, integer(), list("first", "first", "last"), classed,
                I(c("first", "first", "last")), dimensional,
                array(c("first", "last", "first", "last"), c(2L, 1L, 2L)))
  for (values in cases) {
    expect_identical(gene_id_byte_key(values),
                     fast_adapter_scalar_byte_key(values))
  }
  for (values in list(1:2, c(TRUE, FALSE), factor(c("first", "second")))) {
    expect_error(fast_adapter_scalar_byte_key(values), "character")
    expect_error(gene_id_byte_key(values), "character")
  }
})

test_that("restoration preserves complete results for equal bytes and empty ledgers", {
  expected <- fast_adapter_result_fixture()
  ids <- expected$input$gene_ids
  components <- c("state_ledger", "composite_ledger", "gene_provenance",
                  "diagnostics")
  expect_gt(nrow(expected$composite_ledger), 0L)
  expect_gt(nrow(expected$diagnostics), 0L)
  for (mark in c("unknown", "bytes")) {
    candidate <- expected
    for (matrix_name in c("state_matrix", "numeric_matrix")) {
      values <- rownames(candidate[[matrix_name]])
      Encoding(values) <- mark
      rownames(candidate[[matrix_name]]) <- values
    }
    for (component in components) {
      values <- candidate[[component]]$gene_id
      Encoding(values) <- mark
      candidate[[component]]$gene_id <- values
    }
    restored <- restore_gene_id_encodings(candidate, ids)
    expect_identical(restored, expected)
    for (component in components) {
      expect_identical(Encoding(restored[[component]]$gene_id),
                       Encoding(expected[[component]]$gene_id))
      expect_identical(fast_adapter_scalar_byte_key(restored[[component]]$gene_id),
                       fast_adapter_scalar_byte_key(expected[[component]]$gene_id))
    }
  }

  empty <- expected
  empty$composite_ledger <- empty$composite_ledger[FALSE, , drop = FALSE]
  empty$diagnostics <- empty$diagnostics[FALSE, , drop = FALSE]
  # Restoration itself does not validate unrelated result components.
  expect_identical(restore_gene_id_encodings(empty, ids), empty)
})

test_that("restoration rejects byte-distinct axes and malformed or unknown ledger IDs", {
  expected <- fast_adapter_result_fixture()
  ids <- expected$input$gene_ids
  latin1_id <- rawToChar(c(charToRaw("gene_"), as.raw(0xe9)))
  Encoding(latin1_id) <- "latin1"
  invalid_id <- rawToChar(as.raw(c(0xff, 0x28)))
  Encoding(invalid_id) <- "unknown"

  for (matrix_name in c("state_matrix", "numeric_matrix")) {
    for (replacement in list(latin1_id, NA_character_, invalid_id)) {
      candidate <- expected
      values <- rownames(candidate[[matrix_name]])
      values[[1L]] <- replacement
      rownames(candidate[[matrix_name]]) <- values
      expect_error(restore_gene_id_encodings(candidate, ids),
                   "C\\+\\+ result gene axis differs from requested gene order")
    }
  }
  for (component in c("state_ledger", "composite_ledger", "gene_provenance",
                      "diagnostics")) {
    for (replacement in list("unknown_gene", latin1_id, invalid_id,
                             NA_character_)) {
      candidate <- expected
      candidate[[component]]$gene_id[[1L]] <- replacement
      expect_error(restore_gene_id_encodings(candidate, ids),
                   "production result returned an unknown gene ID")
    }
  }
  malformed <- expected
  malformed$state_ledger$gene_id <- seq_len(nrow(malformed$state_ledger))
  expect_error(restore_gene_id_encodings(malformed, ids), "character")
})

test_that("restoration retains the scalar NA key behavior without accepting missing axes", {
  species <- "((A,B),(C,D));"
  tree <- "((A:1,B:2):3,(C:4,D:5):6);"
  expected <- align_branches(species, c(tree, tree), gene_ids = c("NA", "other"))
  candidate <- expected
  candidate$state_ledger$gene_id[[1L]] <- NA_character_
  expect_identical(
    restore_gene_id_encodings(candidate, c("NA", "other")), expected
  )

  rownames(candidate$state_matrix) <- c(NA_character_, "other")
  expect_error(restore_gene_id_encodings(candidate, c("NA", "other")),
               "C\\+\\+ result gene axis differs from requested gene order")
})

test_that("Fast backend identity tampering is rejected even without version checking", {
  species <- "((A,B),(C,D));"
  tree <- "((A:1,B:2):3,(C:4,D:5):6);"
  fixed <- align_branches(species, c(g = tree), mode = "fixed")
  free <- align_branches(species, c(g = tree), mode = "free")
  validate_result <- SplitAlignerR:::validate_splitaligner_result_object
  expect_no_error(validate_result(free))
  expect_no_error(validate_result(free, check_version = FALSE))

  wrong <- list(
    backend_name = "other-backend", backend_abi = 3L,
    backend_source_commit = paste(rep("0", 40L), collapse = "")
  )
  for (field in names(wrong)) {
    for (replacement in list(wrong[[field]], NULL)) {
      candidate <- free
      candidate$metadata[[field]] <- replacement
      message <- paste0("metadata field `", field, "` is inconsistent")
      expect_error(validate_result(candidate), message)
      expect_error(validate_result(candidate, check_version = FALSE), message)
      expect_error(pair_alignment_results(fixed, candidate), message)
    }
  }
  wrong_type <- free
  wrong_type$metadata$backend_abi <- 2
  expect_error(validate_result(wrong_type, check_version = FALSE),
               "metadata field `backend_abi` is inconsistent")
})

test_that("public display and summary retain the actual Fast backend identity", {
  result <- fast_adapter_result_fixture()
  returned <- NULL
  printed <- capture.output(returned <- print(result))
  expect_identical(returned, result)
  expect_true(any(grepl(
    "core=0.2.0-fast-abi2  schema=1.0.0  mode=free", printed, fixed = TRUE
  )))
  summary_result <- summary(result)
  expect_identical(summary_result$metadata, result$metadata)
  expect_identical(summary_result$metadata$backend_name, "SplitAlignerFast")
  expect_identical(summary_result$metadata$backend_abi, 2L)
})
