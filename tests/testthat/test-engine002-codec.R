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

test_that("ENGINE002 golden codec is deterministic and direct-view exact", {
  authority <- e2_authority()
  record <- e2_three_taxon_record(authority, 17)
  decoded <- SplitAlignerR:::.engine002_plan_decode(authority, record)
  view <- SplitAlignerR:::.engine002_plan_view_snapshot(authority, record)

  expect_identical(decoded, view)
  expect_identical(decoded$pattern_id, 17)
  expect_identical(decoded$retained, e2_raw(7L))
  expect_identical(decoded$states, c(0L, 0L, 2L, 1L, 2L))
  expect_identical(decoded$eligible_primitives, c(0L, 1L))
  expect_identical(decoded$fibers, list(c(2L, 4L)))
  expect_identical(decoded$fiber_queries, list(e2_raw(4L)))
  expect_identical(
    SplitAlignerR:::.engine002_plan_encode(
      authority, decoded$pattern_id, decoded$retained, decoded$states,
      decoded$primitive_queries
    ),
    record
  )
  expect_identical(rawToChar(record[1:4]), "TPLN")
  expect_identical(length(record[1:144]), 144L)
  fixture <- readLines(test_path(
    "fixtures", "engine002", "plan_three_taxon_dense_v1.hex"
  ), warn = FALSE)
  expect_identical(
    paste(sprintf("%02x", as.integer(record)), collapse = ""), fixture
  )
  probe <- SplitAlignerR:::.engine002_plan_view_probe(
    authority, record, 0:4, repeats = 2L
  )
  expect_identical(probe$pattern_id, 17)
  expect_identical(probe$state_sum, 10)
  expect_identical(probe$query_bytes, 8)
})

test_that("ENGINE002 two/three-taxon boundaries and terminal fibers hold", {
  authority <- e2_authority()
  two <- SplitAlignerR:::.engine002_plan_decode(
    authority, e2_two_taxon_record(authority)
  )
  three <- SplitAlignerR:::.engine002_plan_decode(
    authority, e2_three_taxon_record(authority)
  )
  expect_identical(two$states, c(2L, 2L, 1L, 1L, 1L))
  expect_identical(two$fibers, list(c(0L, 1L)))
  expect_false(any(two$states[1:2] == 1L))
  expect_identical(three$fibers, list(c(2L, 4L)))
  expect_false(any(three$states[1:3] == 1L))
})

test_that("ENGINE002 rejects zero/one retained taxa and reserved truth state", {
  authority <- e2_authority()
  expect_error(
    SplitAlignerR:::.engine002_plan_encode(
      authority, 0, e2_raw(0L), rep(1L, 5L), rep(list(NULL), 5L)
    ),
    "ENGINE_SCIENTIFIC_INVARIANT"
  )
  expect_error(
    SplitAlignerR:::.engine002_plan_encode(
      authority, 0, e2_raw(1L), c(0L, 1L, 1L, 1L, 1L),
      list(e2_raw(1L), NULL, NULL, NULL, NULL)
    ),
    "ENGINE_SCIENTIFIC_INVARIANT"
  )
  expect_error(
    SplitAlignerR:::.engine002_plan_encode(
      authority, 0, e2_raw(3L), c(3L, 2L, 1L, 1L, 1L),
      list(e2_raw(1L), e2_raw(1L), NULL, NULL, NULL)
    ),
    "ENGINE_SCIENTIFIC_INVARIANT"
  )
})

test_that("ENGINE002 hashes match independent public vectors", {
  vectors <- SplitAlignerR:::cpp_engine002_hash_reference_vectors()
  expect_identical(
    vectors$xxhash64_seed0,
    c("ef46db3751d8e999", "d24ec4f1a98c6e5b", "44bc2cf5ad770999")
  )
  expect_identical(
    vectors$sha256,
    c(
      "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
  )
})
