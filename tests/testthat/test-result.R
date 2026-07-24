small_fused_result <- function() {
  align_branches(
    "((A:1,B:2):3,(C:4,D:5):6);",
    c(two = "(A:4,B:5);", full = "((A:1,B:2):3,(C:4,D:5):6);")
  )
}

test_that("coordinate provenance exposes stable primitive member sets", {
  result <- small_fused_result()
  all_coordinates <- coordinate_provenance(result)

  expect_identical(all_coordinates, result$coordinate_table)
  expect_identical(
    all_coordinates$coordinate_id,
    c(paste0("B", 1:5), "F[B1|B2]")
  )
  fused <- coordinate_provenance(result, "F[B1|B2]")
  expect_identical(fused$coordinate_type, "composite")
  expect_identical(fused$member_count, 2L)
  expect_identical(fused$primitive_members[[1L]], c("B1", "B2"))

  reordered <- coordinate_provenance(result, c("F[B1|B2]", "B1"))
  expect_identical(reordered$coordinate_id, c("F[B1|B2]", "B1"))
  expect_error(coordinate_provenance(result, "F[unknown]"), "Unknown")
  expect_error(coordinate_provenance(result, NA_character_), "nonempty")
})

test_that("result summary accounts for every primitive cell", {
  result <- small_fused_result()
  summary <- summary(result)

  expect_s3_class(summary, "summary.splitaligner_result")
  expect_identical(sum(summary$state_counts$count),
                   length(result$state_matrix))
  expect_identical(nrow(summary$gene_summary), 2L)
  expect_identical(
    summary$finite_numeric_values,
    sum(!is.na(result$numeric_matrix))
  )
  expect_output(print(result), "2 genes x 5 primitive")
  expect_output(print(summary), "Finite numeric values")
})

test_that("result save and checked reload are lossless", {
  result <- small_fused_result()
  path <- tempfile(fileext = ".rds")
  saved <- save_splitaligner_result(result, path)
  expect_identical(saved, normalizePath(path, winslash = "/"))
  restored <- read_splitaligner_result(path)
  expect_identical(restored, result)
  expect_error(save_splitaligner_result(result, path), "already exists")
  expect_silent(save_splitaligner_result(result, path, overwrite = TRUE))

  incompatible <- result
  incompatible$metadata$schema_version <- "future-schema"
  incompatible_path <- tempfile(fileext = ".rds")
  saveRDS(incompatible, incompatible_path)
  expect_error(read_splitaligner_result(incompatible_path), "incompatible")
  expect_identical(
    read_splitaligner_result(incompatible_path, check_version = FALSE),
    incompatible
  )

  malformed_path <- tempfile(fileext = ".rds")
  saveRDS(list(), malformed_path)
  expect_error(read_splitaligner_result(malformed_path), "must inherit")
})

test_that("result validator rejects cross-component mutations", {
  result <- small_fused_result()
  mutations <- list(
    state_ledger_mismatch = function(x) {
      x$state_ledger$state[[1L]] <- "NA_topo"
      x
    },
    duplicate_state_ledger_row = function(x) {
      x$state_ledger[2L, ] <- x$state_ledger[1L, ]
      x
    },
    missing_state_ledger_row = function(x) {
      x$state_ledger <- x$state_ledger[-1L, , drop = FALSE]
      x
    },
    numeric_axis = function(x) {
      colnames(x$numeric_matrix)[[1L]] <- "wrong-axis"
      x
    },
    composite_member_id = function(x) {
      x$composite_coordinates$primitive_members[[1L]][[2L]] <- "B3"
      x
    },
    composite_member_count = function(x) {
      x$composite_coordinates$member_count[[1L]] <- 3L
      x
    },
    coordinate_table = function(x) {
      x$coordinate_table$member_count[[1L]] <- 9L
      x
    },
    metadata_count = function(x) {
      x$metadata$gene_count <- 99L
      x
    },
    gene_provenance = function(x) {
      x$gene_provenance$retained_taxa_key[[1L]] <- "RT1:tampered"
      x
    },
    conventions = function(x) {
      x$conventions$degree2_policy <- "tampered"
      x
    }
  )

  for (name in names(mutations)) {
    mutated <- mutations[[name]](result)
    expect_error(
      SplitAlignerR:::validate_splitaligner_result_object(mutated),
      "invariant failed",
      info = name
    )
  }

  incompatible <- result
  incompatible$metadata$schema_version <- "future-schema"
  expect_error(
    SplitAlignerR:::validate_splitaligner_result_object(incompatible),
    "incompatible"
  )
  expect_no_error(
    SplitAlignerR:::validate_splitaligner_result_object(
      incompatible, check_version = FALSE
    )
  )
})
