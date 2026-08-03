fix1_mib <- 1024^2
fix1_raw <- function(x) as.raw(x)

fix1_authority <- function() {
  SplitAlignerR:::.engine002_authority(
    c("A", "B", "C", "D"), c(0L, 1L, 2L, 3L, NA_integer_),
    lapply(c(1L, 2L, 4L, 8L, 3L), fix1_raw)
  )
}

fix1_record_ab <- function(authority, id = 0) {
  SplitAlignerR:::.engine002_plan_encode(
    authority, id, fix1_raw(3L), c(2L, 2L, 1L, 1L, 1L),
    list(fix1_raw(1L), fix1_raw(1L), NULL, NULL, NULL)
  )
}

fix1_record_abc <- function(authority, id = 1) {
  SplitAlignerR:::.engine002_plan_encode(
    authority, id, fix1_raw(7L), c(0L, 0L, 2L, 1L, 2L),
    list(
      fix1_raw(1L), fix1_raw(2L), fix1_raw(4L), NULL,
      fix1_raw(4L)
    )
  )
}

fix1_store <- function(authority, records, directory, run_id,
                       cache = 0) {
  patterns <- lapply(records, function(record) {
    SplitAlignerR:::.engine002_plan_decode(authority, record)$retained
  })
  SplitAlignerR:::.engine002_disk_store(
    authority, patterns, directory, run_id,
    cache, fix1_mib, fix1_mib, fix1_mib,
    cache + 3 * fix1_mib
  )
}

test_that("FIX001 streaming insertion contract is exact and monotone", {
  skip_on_cran()
  authority <- fix1_authority()
  records <- list(
    fix1_record_ab(authority, 0),
    fix1_record_abc(authority, 1)
  )
  root <- tempfile("fix001-order-", tmpdir = "/private/tmp")
  dir.create(root, mode = "0700")
  on.exit(unlink(root, recursive = TRUE), add = TRUE)
  make <- function(id) {
    fix1_store(authority, records, root, sprintf("%032x", id))
  }

  out_of_order <- make(1L)
  expect_error(
    SplitAlignerR:::cpp_engine002_store_insert(
      out_of_order, records[[2L]]
    ),
    "ENGINE_PATTERN_MISMATCH.*next contiguous"
  )
  SplitAlignerR:::cpp_engine002_store_close(out_of_order)

  duplicate <- make(2L)
  SplitAlignerR:::cpp_engine002_store_insert(duplicate, records[[1L]])
  expect_error(
    SplitAlignerR:::cpp_engine002_store_insert(
      duplicate, records[[1L]]
    ),
    "ENGINE_DUPLICATE_RECORD"
  )
  SplitAlignerR:::cpp_engine002_store_close(duplicate)

  too_many <- fix1_store(
    authority, records[1L], root, sprintf("%032x", 3L)
  )
  SplitAlignerR:::cpp_engine002_store_insert(too_many, records[[1L]])
  expect_error(
    SplitAlignerR:::cpp_engine002_store_insert(
      too_many, records[[2L]]
    ),
    "ENGINE_PATTERN_MISMATCH.*too many"
  )
  SplitAlignerR:::cpp_engine002_store_close(too_many)

  premature <- make(4L)
  SplitAlignerR:::cpp_engine002_store_insert(premature, records[[1L]])
  expect_error(
    SplitAlignerR:::cpp_engine002_store_finalize(
      premature, root, sprintf("%032x", 4L)
    ),
    "ENGINE_INCOMPLETE_RUN"
  )
  SplitAlignerR:::cpp_engine002_store_close(premature)

  complete <- make(5L)
  lapply(records, function(record) {
    SplitAlignerR:::cpp_engine002_store_insert(complete, record)
  })
  manifest <- SplitAlignerR:::cpp_engine002_store_finalize(
    complete, root, sprintf("%032x", 5L)
  )
  expect_true(file.exists(manifest))
  expect_error(
    SplitAlignerR:::cpp_engine002_store_insert(complete, records[[1L]]),
    "ENGINE_INVALID_STATE"
  )
  expect_true(SplitAlignerR:::cpp_engine002_store_close(complete))
  expect_error(
    SplitAlignerR:::cpp_engine002_store_insert(complete, records[[1L]]),
    "ENGINE_CONTEXT_CLOSED"
  )
})

test_that("FIX001 SHA finalization guards reject hidden invariant breaks", {
  expect_length(SplitAlignerR:::cpp_engine002_sha_invariant_probe(0L), 1L)
  expect_error(
    SplitAlignerR:::cpp_engine002_sha_invariant_probe(1L),
    "ENGINE_INTERNAL_FAILURE.*buffered-byte"
  )
  expect_error(
    SplitAlignerR:::cpp_engine002_sha_invariant_probe(2L),
    "ENGINE_INTERNAL_FAILURE.*bit-length"
  )
})

test_that("FIX001 deterministic I/O faults cannot publish a store", {
  skip_on_cran()
  authority <- fix1_authority()
  record <- fix1_record_ab(authority, 0)
  root <- tempfile("fix001-io-fault-", tmpdir = "/private/tmp")
  dir.create(root, mode = "0700")
  on.exit({
    SplitAlignerR:::cpp_engine002_set_io_faultpoint(0L)
    unlink(root, recursive = TRUE)
  }, add = TRUE)
  finalize_faults <- c(2L, 4L, 5L, 6L, 7L)
  for (fault in 1:9) {
    run_id <- sprintf("%032x", fault + 100L)
    store <- fix1_store(authority, list(record), root, run_id)
    if (fault %in% finalize_faults) {
      SplitAlignerR:::cpp_engine002_store_insert(store, record)
    }
    SplitAlignerR:::cpp_engine002_set_io_faultpoint(fault)
    action <- if (fault %in% finalize_faults) {
      function() {
        SplitAlignerR:::cpp_engine002_store_finalize(store, root, run_id)
      }
    } else {
      function() {
        SplitAlignerR:::cpp_engine002_store_insert(store, record)
      }
    }
    expected <- if (fault == 8L) {
      "ENGINE_DISK_FULL"
    } else if (fault == 9L) {
      "ENGINE_INTERRUPTED"
    } else {
      "ENGINE_IO_FAILURE"
    }
    expect_error(action(), expected)
    expect_false(file.exists(file.path(
      root, paste0(run_id, ".truthstore.manifest")
    )))
    expect_false(file.exists(file.path(
      root, paste0(run_id, ".truthstore.bin")
    )))
    expect_length(list.files(root, pattern = run_id), 0L)
    SplitAlignerR:::cpp_engine002_set_io_faultpoint(0L)
  }
})

test_that("FIX001 constant fast hash preserves all exact domains", {
  skip_on_cran()
  authority <- fix1_authority()
  normal <- fix1_record_abc(authority, 1)
  SplitAlignerR:::cpp_engine002_set_constant_fast_hash(TRUE)
  on.exit(
    SplitAlignerR:::cpp_engine002_set_constant_fast_hash(FALSE),
    add = TRUE
  )
  collision <- fix1_record_abc(authority, 1)
  expect_identical(collision, normal)
  expect_identical(
    unname(SplitAlignerR:::cpp_engine002_constant_hash_registry_probe()),
    rep.int(3L, 7L)
  )

  records <- list(fix1_record_ab(authority, 0), collision)
  memory <- SplitAlignerR:::.engine002_memory_store(authority, 2)
  lapply(records, function(record) {
    SplitAlignerR:::cpp_engine002_store_insert(memory, record)
  })
  SplitAlignerR:::cpp_engine002_store_finalize(memory, "", "")
  expect_identical(
    SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
      memory, 1, fix1_raw(7L)
    )$retained,
    fix1_raw(7L)
  )
  SplitAlignerR:::cpp_engine002_store_close(memory)

  root <- tempfile("fix001-collision-", tmpdir = "/private/tmp")
  dir.create(root, mode = "0700")
  on.exit(unlink(root, recursive = TRUE), add = TRUE)
  run_id <- "ffffffffffffffffffffffffffffffff"
  disk <- fix1_store(authority, records, root, run_id, cache = 1024)
  lapply(records, function(record) {
    SplitAlignerR:::cpp_engine002_store_insert(disk, record)
  })
  SplitAlignerR:::cpp_engine002_store_finalize(disk, root, run_id)
  expect_identical(
    SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
      disk, 0, fix1_raw(3L)
    )$retained,
    fix1_raw(3L)
  )
  expect_identical(
    SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
      disk, 1, fix1_raw(7L)
    )$retained,
    fix1_raw(7L)
  )
  expect_gte(
    SplitAlignerR:::cpp_engine002_store_stats(disk)$misses,
    2
  )
  SplitAlignerR:::cpp_engine002_store_close(disk)
})

test_that("FIX001 returned snapshots are owned copies across close", {
  authority <- fix1_authority()
  record <- fix1_record_ab(authority, 0)
  memory <- SplitAlignerR:::.engine002_memory_store(authority, 1)
  SplitAlignerR:::cpp_engine002_store_insert(memory, record)
  SplitAlignerR:::cpp_engine002_store_finalize(memory, "", "")
  snapshot <- SplitAlignerR:::cpp_engine002_store_lookup_snapshot(
    memory, 0, fix1_raw(3L)
  )
  SplitAlignerR:::cpp_engine002_store_close(memory)
  expect_identical(snapshot$retained, fix1_raw(3L))
  expect_identical(snapshot$states, c(2L, 2L, 1L, 1L, 1L))
})

test_that("FIX001 authority-scale fixture is valid and fresh-process ready", {
  skip_on_cran()
  root <- tempfile("fix001-authority-scale-", tmpdir = "/private/tmp")
  dir.create(root, mode = "0700")
  on.exit(unlink(root, recursive = TRUE), add = TRUE)
  count <- 16
  index_budget <- 16 * fix1_mib
  result <- SplitAlignerR:::cpp_engine002_build_authority_scale_store(
    root, "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee", count,
    0, fix1_mib, index_budget, fix1_mib, index_budget + 2 * fix1_mib
  )
  expect_gte(result$mean_record_bytes, 15 * 1024)
  expect_lte(result$mean_record_bytes, 25 * 1024)
  expect_lte(
    result$builder_charged_high_water,
    result$current_record_high_water + count * 64 + 4096
  )
  phase_fields <- c(
    "finalize_io_seconds", "temporary_validation_seconds",
    "manifest_prepare_seconds", "atomic_publication_seconds",
    "published_validation_seconds"
  )
  expect_true(all(vapply(result[phase_fields], is.numeric, logical(1))))
  expect_true(all(unlist(result[phase_fields], use.names = FALSE) >= 0))
  expect_lte(
    sum(unlist(result[phase_fields], use.names = FALSE)),
    result$finalize_validate_publish_seconds * 1.05
  )
  reopened <- SplitAlignerR:::cpp_engine002_reopen_authority_scale_store(
    result$manifest, count,
    0, fix1_mib, index_budget, fix1_mib, index_budget + 2 * fix1_mib
  )
  expect_identical(reopened$lookup_count, 3L)
  expect_identical(reopened$file_bytes, result$final_store_bytes)
})
