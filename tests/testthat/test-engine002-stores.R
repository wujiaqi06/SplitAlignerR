e2_mib <- 1024^2

e2_raw <- function(x) as.raw(x)

e2_authority <- function() {
  SplitAlignerR:::.engine002_authority(
    c("A", "B", "C", "D"), c(0L, 1L, 2L, 3L, NA_integer_),
    lapply(c(1L, 2L, 4L, 8L, 3L), e2_raw)
  )
}

e2_two_taxon_record <- function(authority = e2_authority(), id = 0) {
  SplitAlignerR:::.engine002_plan_encode(
    authority, id, e2_raw(3L), c(2L, 2L, 1L, 1L, 1L),
    list(e2_raw(1L), e2_raw(1L), NULL, NULL, NULL)
  )
}

e2_three_taxon_record <- function(authority = e2_authority(), id = 0) {
  SplitAlignerR:::.engine002_plan_encode(
    authority, id, e2_raw(7L), c(0L, 0L, 2L, 1L, 2L),
    list(e2_raw(1L), e2_raw(2L), e2_raw(4L), NULL, e2_raw(4L))
  )
}

e2_two_taxon_cd_record <- function(authority = e2_authority(), id = 1) {
  SplitAlignerR:::.engine002_plan_encode(
    authority, id, e2_raw(12L), c(1L, 1L, 2L, 2L, 1L),
    list(NULL, NULL, e2_raw(4L), e2_raw(4L), NULL)
  )
}

e2_disk_store <- function(authority, count, cache = 0, scratch = e2_mib) {
  SplitAlignerR:::.engine002_disk_store(
    authority, count, cache, scratch, e2_mib, e2_mib,
    cache + scratch + 2 * e2_mib
  )
}

e2_u64_from_raw <- function(bytes, zero_offset) {
  value <- as.double(as.integer(
    bytes[(zero_offset + 1L):(zero_offset + 8L)]
  ))
  sum(value * 256^(0:7))
}

test_that("ENGINE002 memory store lifecycle is pin safe and canonical", {
  authority <- e2_authority()
  records <- list(
    e2_two_taxon_record(authority, 0),
    e2_three_taxon_record(authority, 1)
  )
  store <- SplitAlignerR:::.engine002_memory_store(authority, 2)
  expect_error(
    SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
      store, 0, e2_raw(3L)
    ),
    "ENGINE_INVALID_STATE"
  )
  expect_true(SplitAlignerR:::cpp_engine002_store_insert(store, records[[2L]]))
  expect_true(SplitAlignerR:::cpp_engine002_store_insert(store, records[[1L]]))
  expect_true(SplitAlignerR:::cpp_engine002_store_finalize(store, "", ""))
  before <- SplitAlignerR:::cpp_engine002_store_stats(store)
  expect_true(SplitAlignerR:::cpp_engine002_store_finalize(store, "", ""))
  after <- SplitAlignerR:::cpp_engine002_store_stats(store)
  expect_identical(before, after)
  pin <- SplitAlignerR:::cpp_engine002_store_debug_pin(store, 0, e2_raw(3L))
  expect_error(SplitAlignerR:::cpp_engine002_store_close(store),
               "ENGINE_STORE_BUSY")
  expect_true(SplitAlignerR:::cpp_engine002_pin_release(pin))
  expect_true(SplitAlignerR:::cpp_engine002_store_close(store))
  expect_true(SplitAlignerR:::cpp_engine002_store_close(store))
  expect_error(SplitAlignerR:::cpp_engine002_store_stats(store),
               "ENGINE_CONTEXT_CLOSED")
})

test_that("ENGINE002 duplicate and missing pattern identities fail exactly", {
  authority <- e2_authority()
  record <- e2_two_taxon_record(authority, 0)
  duplicate_id <- SplitAlignerR:::.engine002_memory_store(authority, 2)
  SplitAlignerR:::cpp_engine002_store_insert(duplicate_id, record)
  expect_error(
    SplitAlignerR:::cpp_engine002_store_insert(duplicate_id, record),
    "ENGINE_DUPLICATE_RECORD"
  )
  expect_error(
    SplitAlignerR:::cpp_engine002_store_finalize(duplicate_id, "", ""),
    "ENGINE_PATTERN_MISMATCH"
  )
})

test_that("ENGINE002 disk store is durable, bounded, and manifest gated", {
  skip_on_cran()
  authority <- e2_authority()
  records <- list(
    e2_two_taxon_record(authority, 0),
    e2_three_taxon_record(authority, 1)
  )
  destination <- tempfile("engine002-test-", tmpdir = "/private/tmp")
  dir.create(destination, mode = "0700")
  on.exit(unlink(destination, recursive = TRUE), add = TRUE)
  store <- e2_disk_store(authority, 2)
  lapply(rev(records), function(x) {
    SplitAlignerR:::cpp_engine002_store_insert(store, x)
  })
  manifest <- SplitAlignerR:::cpp_engine002_store_finalize(
    store, destination, "0123456789abcdef0123456789abcdef"
  )
  expect_true(file.exists(manifest))
  component <- sub("[.]manifest$", ".bin", manifest)
  component_bytes <- readBin(
    component, raw(), n = file.info(component)$size
  )
  hex <- function(value) paste(
    sprintf("%02x", as.integer(value)), collapse = ""
  )
  golden <- utils::read.delim(
    test_path("fixtures", "engine002", "store_two_pattern_v1.tsv"),
    header = FALSE, quote = "", stringsAsFactors = FALSE
  )
  expected <- stats::setNames(golden[[2L]], golden[[1L]])
  index_offset <- e2_u64_from_raw(component_bytes, 56L)
  footer_offset <- e2_u64_from_raw(component_bytes, 64L)
  expect_identical(hex(component_bytes[1:256]), expected[["store_header"]])
  expect_identical(
    hex(component_bytes[(index_offset + 1L):footer_offset]),
    expected[["index"]]
  )
  expect_identical(
    hex(component_bytes[(footer_offset + 1L):length(component_bytes)]),
    expected[["footer"]]
  )
  expect_identical(
    hex(readBin(manifest, raw(), n = file.info(manifest)$size)),
    expected[["manifest_hex"]]
  )
  expect_identical(as.character(length(component_bytes)),
                   expected[["store_bytes"]])
  first <- SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
    store, 0, e2_raw(3L)
  )
  stats <- SplitAlignerR:::cpp_engine002_store_stats(store)
  expect_lte(stats$charged_cache_bytes, 0)
  expect_lte(stats$scratch_high_water, e2_mib)
  expect_true(SplitAlignerR:::cpp_engine002_store_close(store))

  reopened <- SplitAlignerR:::cpp_engine002_disk_store_open(
    authority, manifest, 64 * 1024, e2_mib, e2_mib, e2_mib,
    3 * e2_mib + 64 * 1024
  )
  expect_identical(
    SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
      reopened, 0, e2_raw(3L)
    ),
    first
  )
  expect_true(SplitAlignerR:::cpp_engine002_store_close(reopened))

  orphan <- sub("[.]manifest$", ".missing.manifest", manifest)
  expect_error(
    SplitAlignerR:::cpp_engine002_disk_store_open(
      authority, orphan, 0, e2_mib, e2_mib, e2_mib, 3 * e2_mib
    ),
    "ENGINE_"
  )
})

test_that("ENGINE002 atomic failpoints never publish an accepted manifest", {
  skip_on_cran()
  authority <- e2_authority()
  destination <- tempfile("engine002-failpoints-", tmpdir = "/private/tmp")
  dir.create(destination, mode = "0700")
  on.exit({
    SplitAlignerR:::cpp_engine002_set_publication_failpoint(0L)
    unlink(destination, recursive = TRUE)
  }, add = TRUE)
  for (stage in 1:15) {
    run_id <- sprintf("%032x", stage)
    store <- e2_disk_store(authority, 1)
    SplitAlignerR:::cpp_engine002_store_insert(
      store, e2_two_taxon_record(authority, 0)
    )
    SplitAlignerR:::cpp_engine002_set_publication_failpoint(stage)
    expect_error(
      SplitAlignerR:::cpp_engine002_store_finalize(
        store, destination, run_id
      ),
      "ENGINE_IO_FAILURE"
    )
    expect_false(file.exists(file.path(
      destination, paste0(run_id, ".truthstore.manifest")
    )))
  }
  SplitAlignerR:::cpp_engine002_set_publication_failpoint(0L)
})

test_that("ENGINE002 disk corruption and no-clobber publication are rejected", {
  skip_on_cran()
  authority <- e2_authority()
  destination <- tempfile("engine002-corrupt-", tmpdir = "/private/tmp")
  dir.create(destination, mode = "0700")
  on.exit(unlink(destination, recursive = TRUE), add = TRUE)
  run_id <- "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  create <- function() {
    store <- e2_disk_store(authority, 2)
    SplitAlignerR:::cpp_engine002_store_insert(
      store, e2_two_taxon_record(authority, 0)
    )
    SplitAlignerR:::cpp_engine002_store_insert(
      store, e2_three_taxon_record(authority, 1)
    )
    store
  }
  original_store <- create()
  manifest <- SplitAlignerR:::cpp_engine002_store_finalize(
    original_store, destination, run_id
  )
  SplitAlignerR:::cpp_engine002_store_close(original_store)
  component <- file.path(destination, paste0(run_id, ".truthstore.bin"))
  original <- readBin(component, raw(), n = file.info(component)$size)
  index_offset <- e2_u64_from_raw(original, 56L)
  footer_offset <- e2_u64_from_raw(original, 64L)
  positions <- c(header = 1L, records = 257L,
                 index = index_offset + 1L, footer = footer_offset + 1L)
  for (position in positions) {
    corrupted <- original
    corrupted[[position]] <- as.raw(bitwXor(
      as.integer(corrupted[[position]]), 1L
    ))
    con <- file(component, open = "wb")
    writeBin(corrupted, con)
    close(con)
    expect_error(
      SplitAlignerR:::cpp_engine002_disk_store_open(
        authority, manifest, 0, e2_mib, e2_mib, e2_mib, 3 * e2_mib
      ),
      "ENGINE_"
    )
  }
  con <- file(component, open = "wb")
  writeBin(original[-length(original)], con)
  close(con)
  expect_error(
    SplitAlignerR:::cpp_engine002_disk_store_open(
      authority, manifest, 0, e2_mib, e2_mib, e2_mib, 3 * e2_mib
    ),
    "ENGINE_"
  )
  con <- file(component, open = "wb")
  writeBin(original, con)
  close(con)

  second <- create()
  expect_error(
    SplitAlignerR:::cpp_engine002_store_finalize(
      second, destination, run_id
    ),
    "ENGINE_"
  )
  expect_identical(
    readBin(component, raw(), n = file.info(component)$size), original
  )
})

test_that("ENGINE002 constant fast-hash buckets preserve exact patterns", {
  authority <- e2_authority()
  records <- list(
    e2_two_taxon_record(authority, 0),
    e2_three_taxon_record(authority, 1)
  )
  constant_hash <- rep("0000000000000000", length(records))
  expect_identical(length(unique(constant_hash)), 1L)
  store <- SplitAlignerR:::.engine002_memory_store(authority, 2)
  lapply(records, function(record) {
    SplitAlignerR:::cpp_engine002_store_insert(store, record)
  })
  SplitAlignerR:::cpp_engine002_store_finalize(store, "", "")
  expect_identical(
    SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
      store, 0, e2_raw(3L)
    )$retained,
    e2_raw(3L)
  )
  expect_identical(
    SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
      store, 1, e2_raw(7L)
    )$retained,
    e2_raw(7L)
  )
})

test_that("ENGINE002 LRU and scratch budgets are hard at boundary values", {
  skip_on_cran()
  authority <- e2_authority()
  destination <- tempfile("engine002-lru-", tmpdir = "/private/tmp")
  dir.create(destination, mode = "0700")
  on.exit(unlink(destination, recursive = TRUE), add = TRUE)
  build <- e2_disk_store(authority, 2)
  SplitAlignerR:::cpp_engine002_store_insert(
    build, e2_two_taxon_record(authority, 0)
  )
  SplitAlignerR:::cpp_engine002_store_insert(
    build, e2_two_taxon_cd_record(authority, 1)
  )
  manifest <- SplitAlignerR:::cpp_engine002_store_finalize(
    build, destination, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  )
  SplitAlignerR:::cpp_engine002_store_close(build)

  open_budget <- function(cache, scratch) {
    SplitAlignerR:::cpp_engine002_disk_store_open(
      authority, manifest, cache, scratch, e2_mib, e2_mib,
      cache + scratch + 2 * e2_mib
    )
  }
  expect_error(
    open_budget(0, 0),
    "ENGINE_MEMORY_BUDGET"
  )

  scratch <- open_budget(0, e2_mib)
  SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
    scratch, 0, e2_raw(3L)
  )
  scratch_stats <- SplitAlignerR:::cpp_engine002_store_stats(scratch)
  expect_identical(scratch_stats$charged_cache_bytes, 0)
  expect_identical(scratch_stats$oversized_bypasses, 1)
  SplitAlignerR:::cpp_engine002_store_close(scratch)

  probe <- open_budget(4096, e2_mib)
  SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
    probe, 0, e2_raw(3L)
  )
  one_charge <- SplitAlignerR:::cpp_engine002_store_stats(
    probe
  )$charged_cache_bytes
  expect_gt(one_charge, 0)
  SplitAlignerR:::cpp_engine002_store_close(probe)

  exact <- open_budget(one_charge, e2_mib)
  pin <- SplitAlignerR:::cpp_engine002_store_debug_pin(
    exact, 0, e2_raw(3L)
  )
  expect_error(
    SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
      exact, 1, e2_raw(12L)
    ),
    "ENGINE_MEMORY_BUDGET"
  )
  expect_gte(SplitAlignerR:::cpp_engine002_store_stats(exact)$pin_failures, 1)
  SplitAlignerR:::cpp_engine002_pin_release(pin)
  SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
    exact, 1, e2_raw(12L)
  )
  exact_stats <- SplitAlignerR:::cpp_engine002_store_stats(exact)
  expect_lte(exact_stats$charged_cache_bytes, one_charge)
  expect_gte(exact_stats$evictions, 1)
  SplitAlignerR:::cpp_engine002_store_close(exact)

  for (budget in c(32, 64) * e2_mib) {
    roomy <- open_budget(budget, e2_mib)
    SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
      roomy, 0, e2_raw(3L)
    )
    expect_lte(
      SplitAlignerR:::cpp_engine002_store_stats(roomy)$charged_cache_bytes,
      budget
    )
    SplitAlignerR:::cpp_engine002_store_close(roomy)
  }
})
