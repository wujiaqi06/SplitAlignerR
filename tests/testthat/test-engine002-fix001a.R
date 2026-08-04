fix1a_mib <- 1024^2
fix1a_raw <- function(x) as.raw(x)

fix1a_authority <- function() {
  SplitAlignerR:::.engine002_authority(
    c("A", "B", "C", "D"), c(0L, 1L, 2L, 3L, NA_integer_),
    lapply(c(1L, 2L, 4L, 8L, 3L), fix1a_raw)
  )
}

fix1a_record <- function(authority) {
  SplitAlignerR:::.engine002_plan_encode(
    authority, 0, fix1a_raw(3L), c(2L, 2L, 1L, 1L, 1L),
    list(fix1a_raw(1L), fix1a_raw(1L), NULL, NULL, NULL)
  )
}

test_that("FIX001A R boundary preserves u64 values above 4 GiB", {
  result <- SplitAlignerR:::.engine002_large_offset_arithmetic_probe(
    16000, 275000
  )
  expect_identical(result$records_bytes, 4400000000)
  expect_identical(result$index_offset, 4400000256)
  expect_gt(result$footer_offset, 2^32)
  expect_gt(result$file_bytes, 2^32)
  expect_true(result$crosses_2GiB)
  expect_true(result$crosses_4GiB)
})

test_that("FIX001A active pins and XPtr finalizers are safe through R", {
  authority <- fix1a_authority()
  record <- fix1a_record(authority)
  store <- SplitAlignerR:::.engine002_memory_store(authority, 1)
  expect_true(SplitAlignerR:::cpp_engine002_store_insert(store, record))
  expect_true(SplitAlignerR:::cpp_engine002_store_finalize(store, "", ""))
  pin <- SplitAlignerR:::cpp_engine002_store_debug_pin(
    store, 0, fix1a_raw(3L)
  )
  expect_error(
    SplitAlignerR:::cpp_engine002_store_close(store), "ENGINE_STORE_BUSY"
  )
  expect_true(SplitAlignerR:::cpp_engine002_pin_release(pin))
  expect_true(SplitAlignerR:::cpp_engine002_store_close(store))
  expect_true(SplitAlignerR:::cpp_engine002_store_close(store))
  expect_error(
    SplitAlignerR:::cpp_engine002_store_stats(store), "ENGINE_CONTEXT_CLOSED"
  )

  for (i in seq_len(20L)) {
    local({
      x <- SplitAlignerR:::.engine002_memory_store(authority, 1)
      SplitAlignerR:::cpp_engine002_store_insert(x, record)
      SplitAlignerR:::cpp_engine002_store_finalize(x, "", "")
      p <- SplitAlignerR:::cpp_engine002_store_debug_pin(x, 0, fix1a_raw(3L))
      invisible(NULL)
    })
  }
  expect_silent(gc())
})

test_that("FIX001A disk path is binary and no-replace on this platform", {
  skip_on_cran()
  authority <- fix1a_authority()
  record <- fix1a_record(authority)
  root <- tempfile(
    "fix001a-disk-", tmpdir = normalizePath(tempdir(), mustWork = TRUE)
  )
  dir.create(root, mode = "0700")
  on.exit(unlink(root, recursive = TRUE, force = TRUE), add = TRUE)
  run_id <- "abcdabcdabcdabcdabcdabcdabcdabcd"
  make_store <- function() {
    SplitAlignerR:::.engine002_disk_store(
      authority, list(fix1a_raw(3L)), root, run_id,
      0, fix1a_mib, fix1a_mib, fix1a_mib, 3 * fix1a_mib
    )
  }
  first <- make_store()
  SplitAlignerR:::cpp_engine002_store_insert(first, record)
  manifest <- SplitAlignerR:::cpp_engine002_store_finalize(first, root, run_id)
  component <- sub("[.]manifest$", ".bin", manifest)
  original <- readBin(component, raw(), n = file.info(component)$size)
  expect_identical(rawToChar(original[1:8]), "SATRST01")
  SplitAlignerR:::cpp_engine002_store_close(first)

  second <- make_store()
  SplitAlignerR:::cpp_engine002_store_insert(second, record)
  expect_error(
    SplitAlignerR:::cpp_engine002_store_finalize(second, root, run_id),
    "ENGINE_"
  )
  expect_identical(
    readBin(component, raw(), n = file.info(component)$size), original
  )
})
