fix1b_mib <- 1024^2
fix1b_run_id <- "0123456789abcdef0123456789abcdef"

fix1b_raw <- function(value) as.raw(value)

fix1b_authority <- function() {
  SplitAlignerR:::.engine002_authority(
    c("A", "B", "C", "D"), c(0L, 1L, 2L, 3L, NA_integer_),
    lapply(c(1L, 2L, 4L, 8L, 3L), fix1b_raw)
  )
}

fix1b_records <- function(authority) {
  list(
    SplitAlignerR:::.engine002_plan_encode(
      authority, 0, fix1b_raw(3L), c(2L, 2L, 1L, 1L, 1L),
      list(fix1b_raw(1L), fix1b_raw(1L), NULL, NULL, NULL)
    ),
    SplitAlignerR:::.engine002_plan_encode(
      authority, 1, fix1b_raw(7L), c(0L, 0L, 2L, 1L, 2L),
      list(
        fix1b_raw(1L), fix1b_raw(2L), fix1b_raw(4L), NULL,
        fix1b_raw(4L)
      )
    )
  )
}

fix1b_u64 <- function(bytes, zero_offset) {
  value <- as.double(as.integer(
    bytes[(zero_offset + 1L):(zero_offset + 8L)]
  ))
  sum(value * 256^(0:7))
}

fix1b_hex <- function(value) {
  paste(sprintf("%02x", as.integer(value)), collapse = "")
}

fix1b_build_store <- function(root) {
  authority <- fix1b_authority()
  records <- fix1b_records(authority)
  patterns <- lapply(records, function(record) {
    SplitAlignerR:::.engine002_plan_decode(authority, record)$retained
  })
  store <- SplitAlignerR:::.engine002_disk_store(
    authority, patterns, root, fix1b_run_id,
    0, fix1b_mib, fix1b_mib, fix1b_mib, 3 * fix1b_mib
  )
  lapply(records, function(record) {
    SplitAlignerR:::cpp_engine002_store_insert(store, record)
  })
  manifest <- SplitAlignerR:::cpp_engine002_store_finalize(
    store, root, fix1b_run_id
  )
  SplitAlignerR:::cpp_engine002_store_close(store)
  list(
    authority = authority,
    manifest = manifest,
    component = sub("[.]manifest$", ".bin", manifest)
  )
}

fix1b_copy_fixture <- function(stem, root) {
  component <- file.path(root, paste0(fix1b_run_id, ".truthstore.bin"))
  manifest <- file.path(root, paste0(fix1b_run_id, ".truthstore.manifest"))
  expect_true(file.copy(
    test_path(
      "fixtures", "engine002", "fix001b", paste0(stem, ".truthstore.bin")
    ),
    component
  ))
  expect_true(file.copy(
    test_path(
      "fixtures", "engine002", "fix001b",
      paste0(stem, ".truthstore.manifest")
    ),
    manifest
  ))
  manifest
}

test_that("FIX001B corrected builder writes the standard payload aggregate", {
  skip_on_cran()
  root <- tempfile(
    "fix001b-standard-", tmpdir = normalizePath(tempdir(), mustWork = TRUE)
  )
  dir.create(root, mode = "0700")
  on.exit(unlink(root, recursive = TRUE, force = TRUE), add = TRUE)
  built <- fix1b_build_store(root)
  bytes <- readBin(
    built$component, raw(), n = file.info(built$component)$size
  )
  footer_offset <- fix1b_u64(bytes, 64L)
  aggregate <- bytes[
    (footer_offset + 48L + 1L):(footer_offset + 80L)
  ]
  expect_identical(
    fix1b_hex(aggregate),
    "86fc58c3816a0b2424d9bdaf1f1b3f93744e6e3ab6ed31e04b2ab138d617fa73"
  )
})

test_that("FIX001B rejects the preserved FIX001A nonstandard golden store", {
  skip_on_cran()
  root <- tempfile(
    "fix001b-old-golden-",
    tmpdir = normalizePath(tempdir(), mustWork = TRUE)
  )
  dir.create(root, mode = "0700")
  on.exit(unlink(root, recursive = TRUE, force = TRUE), add = TRUE)
  component <- file.path(root, paste0(fix1b_run_id, ".truthstore.bin"))
  manifest <- file.path(root, paste0(fix1b_run_id, ".truthstore.manifest"))
  expect_true(file.copy(
    test_path(
      "fixtures", "engine002", "history",
      "fix001a_nonconforming_payload_aggregate.truthstore.bin"
    ),
    component
  ))
  expect_true(file.copy(
    test_path(
      "fixtures", "engine002", "history",
      "fix001a_nonconforming_payload_aggregate.truthstore.manifest"
    ),
    manifest
  ))
  expect_error(
    SplitAlignerR:::cpp_engine002_disk_store_open(
      fix1b_authority(), manifest, 0, fix1b_mib, fix1b_mib,
      fix1b_mib, 3 * fix1b_mib
    ),
    "ENGINE_STORE_CORRUPT.*payload aggregate SHA-256 mismatch"
  )
})

test_that("FIX001B footer-only aggregate mutation fails at footer integrity", {
  skip_on_cran()
  root <- tempfile(
    "fix001b-footer-only-",
    tmpdir = normalizePath(tempdir(), mustWork = TRUE)
  )
  dir.create(root, mode = "0700")
  on.exit(unlink(root, recursive = TRUE, force = TRUE), add = TRUE)
  built <- fix1b_build_store(root)
  bytes <- readBin(
    built$component, raw(), n = file.info(built$component)$size
  )
  footer_offset <- fix1b_u64(bytes, 64L)
  position <- footer_offset + 48L + 1L
  bytes[[position]] <- as.raw(bitwXor(as.integer(bytes[[position]]), 1L))
  connection <- file(built$component, open = "wb")
  writeBin(bytes, connection)
  close(connection)
  expect_error(
    SplitAlignerR:::cpp_engine002_disk_store_open(
      built$authority, built$manifest, 0, fix1b_mib, fix1b_mib,
      fix1b_mib, 3 * fix1b_mib
    ),
    "ENGINE_STORE_CORRUPT.*footer checksum mismatch"
  )
})

test_that("FIX001B aggregate-only self-consistent tamper reaches target gate", {
  skip_on_cran()
  root <- tempfile(
    "fix001b-aggregate-only-",
    tmpdir = normalizePath(tempdir(), mustWork = TRUE)
  )
  dir.create(root, mode = "0700")
  on.exit(unlink(root, recursive = TRUE, force = TRUE), add = TRUE)
  manifest <- fix1b_copy_fixture("aggregate_only_mismatch", root)
  expect_error(
    SplitAlignerR:::cpp_engine002_disk_store_open(
      fix1b_authority(), manifest, 0, fix1b_mib, fix1b_mib,
      fix1b_mib, 3 * fix1b_mib
    ),
    "ENGINE_STORE_CORRUPT.*payload aggregate SHA-256 mismatch"
  )
})

test_that("FIX001B payload mutation reaches the aggregate gate", {
  skip_on_cran()
  root <- tempfile(
    "fix001b-payload-mutation-",
    tmpdir = normalizePath(tempdir(), mustWork = TRUE)
  )
  dir.create(root, mode = "0700")
  on.exit(unlink(root, recursive = TRUE, force = TRUE), add = TRUE)
  manifest <- fix1b_copy_fixture(
    "payload_mutation_aggregate_mismatch", root
  )
  expect_error(
    SplitAlignerR:::cpp_engine002_disk_store_open(
      fix1b_authority(), manifest, 0, fix1b_mib, fix1b_mib,
      fix1b_mib, 3 * fix1b_mib
    ),
    "ENGINE_STORE_CORRUPT.*payload aggregate SHA-256 mismatch"
  )
})
