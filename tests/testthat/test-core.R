test_that("compiled core reports versioned implementation metadata", {
  info <- splitaligner_core_info()
  expect_type(info, "list")
  expect_identical(info$core_version, "0.1.0")
  expect_identical(info$schema_version, "1.0.0")
  expect_identical(info$production_language, "C++17")
  expect_identical(info$numeric_policy, "finite-double-v1")
  expect_false(info$oracle_calls_production_core)
})

test_that("numeric tokens are consumed completely and finite-range checked", {
  tokens <- c(
    "0", "-0", "+1", "1.", ".5", " -2.5e-8 ", "1e-300",
    "1e9999", "1e-9999", "NaN", "-Inf", "NA", "1.2junk", "", NA_character_
  )
  checked <- validate_branch_length_tokens(tokens)

  expect_s3_class(checked, "data.frame")
  expect_identical(checked$token, tokens)
  expect_true(all(checked$accepted[1:7]))
  expect_false(any(checked$accepted[8:15]))
  expect_true(all(is.finite(checked$value[checked$accepted])))
  expect_true(checked$is_zero[1])
  expect_true(checked$is_zero[2])
  expect_false(checked$is_negative[2])
  expect_true(checked$is_negative[6])
  expect_identical(
    checked$classification[8:9],
    c("out_of_range", "out_of_range")
  )
  expect_true(all(
    checked$classification[10:12] == "software_failure_marker"
  ))
  expect_identical(checked$classification[13], "invalid_numeric")
  expect_true(all(checked$classification[14:15] == "missing"))
})

test_that("numeric validator rejects non-character inputs", {
  expect_error(validate_branch_length_tokens(1:3), "character vector")
})

test_that("manual decimal grammar preserves the frozen acceptance corpus", {
  valid <- c(
    "0", "-0", "+0", "1", "1.", ".5", "-.5", "1.5",
    "1e8", "1E+8", "-1.2e-8", "2.2250738585072014e-308",
    "4.9406564584124654e-324"
  )
  valid_checked <- validate_branch_length_tokens(valid)
  expect_true(all(valid_checked$accepted))
  expect_true(all(valid_checked$classification == "finite_numeric"))

  invalid <- c(
    "", "   ", "+", "-", ".", "e1", "1e", "1e+", "1..2",
    "1,5", "1_000", "0x10", "1 2", "1e2x"
  )
  invalid_checked <- validate_branch_length_tokens(invalid)
  expect_false(any(invalid_checked$accepted))
  expect_identical(invalid_checked$classification[1:2], c("missing", "missing"))
  expect_identical(invalid_checked$classification[5], "software_failure_marker")
  expect_true(all(
    invalid_checked$classification[-c(1, 2, 5)] == "invalid_numeric"
  ))

  markers <- c(
    "NA", "na", "N/A", "n/a", ".", "?", "NULL", "null", "NONE",
    "none", "NaN", "nAn", "Inf", "iNF", "Infinity", "INFINITY",
    "+Inf", "-Infinity"
  )
  marker_checked <- validate_branch_length_tokens(markers)
  expect_false(any(marker_checked$accepted))
  expect_true(all(
    marker_checked$classification == "software_failure_marker"
  ))
})
