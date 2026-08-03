e2_raw <- function(x) as.raw(x)

e2_authority <- function() {
  SplitAlignerR:::.engine002_authority(
    c("A", "B", "C", "D"), c(0L, 1L, 2L, 3L, NA_integer_),
    lapply(c(1L, 2L, 4L, 8L, 3L), e2_raw)
  )
}

e2_three_taxon_record <- function(authority = e2_authority(), id = 0) {
  SplitAlignerR:::.engine002_plan_encode(
    authority, id, e2_raw(7L), c(0L, 0L, 2L, 1L, 2L),
    list(e2_raw(1L), e2_raw(2L), e2_raw(4L), NULL, e2_raw(4L))
  )
}

e2_read_u32 <- function(bytes, zero_offset) {
  value <- as.double(as.integer(
    bytes[(zero_offset + 1L):(zero_offset + 4L)]
  ))
  sum(value * c(1, 256, 65536, 16777216))
}

e2_flip <- function(bytes, one_offset) {
  bytes[[one_offset]] <- as.raw(bitwXor(as.integer(bytes[[one_offset]]), 1L))
  bytes
}

test_that("ENGINE002 rejects corruption in every plan logical region", {
  authority <- e2_authority()
  record <- e2_three_taxon_record(authority)
  retained_bytes <- e2_read_u32(record, 28L)
  state_bytes <- e2_read_u32(record, 32L)
  active_count <- e2_read_u32(record, 36L)
  query_count <- e2_read_u32(record, 40L)
  payload <- 145L
  positions <- c(
    magic = 1L,
    header_reserved = 137L,
    retained = payload,
    states = payload + retained_bytes,
    refs = payload + retained_bytes + state_bytes,
    offsets = payload + retained_bytes + state_bytes + 4L * active_count,
    query_pool = payload + retained_bytes + state_bytes +
      4L * active_count + 4L * (query_count + 1L)
  )
  for (position in positions) {
    expect_error(
      SplitAlignerR:::.engine002_plan_decode(
        authority, e2_flip(record, position)
      ),
      "ENGINE_"
    )
  }
  expect_error(
    SplitAlignerR:::.engine002_plan_decode(authority, record[-length(record)]),
    "ENGINE_STORE_CORRUPT"
  )
  expect_error(
    SplitAlignerR:::.engine002_plan_decode(authority, c(record, as.raw(0))),
    "ENGINE_STORE_CORRUPT"
  )
})

test_that("ENGINE002 wrong authority and noncanonical patterns are rejected", {
  authority <- e2_authority()
  record <- e2_three_taxon_record(authority)
  wrong <- SplitAlignerR:::.engine002_authority(
    c("A", "B", "C", "E"), c(0L, 1L, 2L, 3L, NA_integer_),
    lapply(c(1L, 2L, 4L, 8L, 3L), e2_raw)
  )
  expect_error(
    SplitAlignerR:::.engine002_plan_decode(wrong, record),
    "ENGINE_AUTHORITY_MISMATCH"
  )
  bad_padding <- record
  bad_padding[[145L]] <- as.raw(bitwOr(as.integer(bad_padding[[145L]]), 128L))
  expect_error(
    SplitAlignerR:::.engine002_plan_decode(authority, bad_padding),
    "ENGINE_"
  )
})
