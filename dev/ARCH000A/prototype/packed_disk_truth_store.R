## ARCH000A deterministic packed disk truth-plan store.
## The format is experimental and deliberately outside the package runtime.

a_adler32 <- function(bytes) {
  modulus <- 65521
  s1 <- 1
  s2 <- 0
  values <- as.integer(bytes)
  if (length(values)) {
    for (start in seq.int(1L, length(values), by = 16384L)) {
      index <- start:min(length(values), start + 16383L)
      chunk <- values[index]
      cumulative <- cumsum(chunk)
      s2 <- (s2 + length(chunk) * s1 + sum(cumulative)) %% modulus
      s1 <- (s1 + sum(chunk)) %% modulus
    }
  }
  paste0(sprintf("%04x", as.integer(s2)), sprintf("%04x", as.integer(s1)))
}

a_pack_states <- function(states) {
  states <- as.integer(states)
  if (anyNA(states) || any(states < 0L) || any(states > 3L)) {
    a_stop("Truth state is outside the two-bit schema.")
  }
  packed <- integer(ceiling(length(states) / 4))
  for (i in seq_along(states)) {
    byte <- ((i - 1L) %/% 4L) + 1L
    shift <- 2L * ((i - 1L) %% 4L)
    packed[[byte]] <- bitwOr(packed[[byte]], bitwShiftL(states[[i]], shift))
  }
  as.raw(packed)
}

a_unpack_states <- function(packed, count) {
  bytes <- as.integer(packed)
  out <- integer(count)
  for (i in seq_len(count)) {
    byte <- ((i - 1L) %/% 4L) + 1L
    shift <- 2L * ((i - 1L) %% 4L)
    out[[i]] <- bitwAnd(bitwShiftR(bytes[[byte]], shift), 3L)
  }
  out
}

a_split_ids_from_key <- function(key) {
  parts <- strsplit(key, ":", fixed = TRUE)[[1L]]
  if (length(parts) != 4L || parts[[1L]] != "SP1") {
    a_stop("Invalid ARCH000 projected-split key.")
  }
  count <- strtoi(parts[[3L]], base = 16L)
  payload <- parts[[4L]]
  if (is.na(count) || count < 1L || nchar(payload) != count * 8L) {
    a_stop("Malformed projected-split payload.")
  }
  starts <- seq.int(1L, nchar(payload), by = 8L)
  vapply(starts, function(i) {
    strtoi(substr(payload, i, i + 7L), base = 16L)
  }, integer(1))
}

a_truth_layout <- function(authority) {
  taxa <- length(authority$taxa)
  primitive <- authority$primitive_count
  key_bytes <- ceiling(taxa / 8)
  state_bytes <- ceiling(primitive / 4)
  body_bytes <- key_bytes + state_bytes + primitive * key_bytes
  list(
    taxa = taxa,
    primitive = primitive,
    key_bytes = key_bytes,
    state_bytes = state_bytes,
    body_bytes = body_bytes,
    record_bytes = body_bytes + 8L,
    header_bytes = 36L,
    footer_bytes = 20L
  )
}

a_pack_truth_plan <- function(plan, authority) {
  layout <- a_truth_layout(authority)
  retained_bits <- a_pack_ids(plan$retained_ids, layout$taxa)
  state_bits <- a_pack_states(plan$state_template)
  query_bytes <- raw(layout$primitive * layout$key_bytes)
  active <- which(!is.na(plan$projected_split))
  for (i in active) {
    ids <- a_split_ids_from_key(plan$projected_split[[i]])
    bits <- a_pack_ids(ids, layout$taxa)
    offset <- (i - 1L) * layout$key_bytes
    query_bytes[offset + seq_len(layout$key_bytes)] <- bits
  }
  body <- c(retained_bits, state_bits, query_bytes)
  a_assert(length(body) == layout$body_bytes, "Packed truth-plan size mismatch.")
  body
}

a_unpack_truth_plan <- function(body, authority) {
  layout <- a_truth_layout(authority)
  a_assert(length(body) == layout$body_bytes, "Packed truth-plan body is truncated.")
  key_index <- seq_len(layout$key_bytes)
  state_index <- layout$key_bytes + seq_len(layout$state_bytes)
  query_start <- layout$key_bytes + layout$state_bytes
  retained <- which(as.logical(rawToBits(body[key_index]))[seq_len(layout$taxa)])
  states <- a_unpack_states(body[state_index], layout$primitive)
  projected <- rep.int(NA_character_, layout$primitive)
  query_bytes <- body[query_start + seq_len(layout$primitive * layout$key_bytes)]
  query_bits <- matrix(
    as.logical(rawToBits(query_bytes)),
    nrow = layout$key_bytes * 8L, ncol = layout$primitive
  )
  query_bits <- query_bits[seq_len(layout$taxa), , drop = FALSE]
  active_query <- which(colSums(query_bits) > 0L)
  for (i in active_query) {
    projected[[i]] <- arch_split_key(which(query_bits[, i]), retained)
  }
  active <- which(!is.na(projected))
  grouped <- split(active, projected[active], drop = TRUE)
  composites <- list()
  for (query in names(grouped)) {
    members <- sort(as.integer(grouped[[query]]), method = "radix")
    fused <- members[states[members] == 2L]
    if (length(fused)) {
      a_assert(
        length(fused) == length(members) && length(fused) > 1L,
        "Packed truth plan contains an invalid composite fiber."
      )
      key <- arch_member_key(fused)
      composites[[key]] <- list(
        key = key, members = fused, projected_split = query
      )
    }
  }
  plan <- list(
    pattern_key = arch_pattern_key(retained),
    retained_ids = retained,
    state_template = states,
    projected_split = projected,
    side_a_size = NULL,
    side_b_size = NULL,
    composites = composites,
    eligible = which(states == 0L),
    bytes = NA_real_
  )
  plan$bytes <- as.numeric(object.size(plan))
  plan
}

a_write_i32 <- function(connection, values) {
  writeBin(as.integer(values), connection, size = 4L, endian = "little")
}

a_read_i32 <- function(connection, count = 1L) {
  readBin(connection, integer(), n = count, size = 4L, endian = "little")
}

a_write_packed_store <- function(path, registry, authority,
                                 complete = TRUE,
                                 max_patterns = length(registry$pattern_ids),
                                 body_provider = NULL,
                                 bstar_threshold_bytes = 32 * 1024^2) {
  layout <- a_truth_layout(authority)
  expected <- length(registry$pattern_ids)
  max_patterns <- min(as.integer(max_patterns), expected)
  con <- file(path, open = "wb")
  on.exit(close(con), add = TRUE)
  writeBin(charToRaw("SARATP01"), con)
  a_write_i32(con, c(
    1L, layout$taxa, layout$primitive, expected, layout$key_bytes,
    layout$state_bytes, layout$record_bytes
  ))
  checksums <- character(max_patterns)
  plan_bytes <- numeric(max_patterns)
  pack_seconds <- build_seconds <- write_seconds <- 0
  bstar <- arch_new_bstar_accumulator(bstar_threshold_bytes)
  roundtrip_equal <- logical(max_patterns)
  for (i in seq_len(max_patterns)) {
    pattern_id <- registry$pattern_ids[[i]]
    if (is.null(body_provider)) {
      timed <- a_elapsed(a_plan_for_pattern(registry, authority, pattern_id))
      plan <- timed$value
      build_seconds <- build_seconds + timed$seconds
      plan_bytes[[i]] <- as.numeric(object.size(plan))
      if (length(plan$composites)) {
        for (composite in plan$composites) {
          arch_bstar_add(bstar, composite$members)
        }
      }
      timed <- a_elapsed(a_pack_truth_plan(plan, authority))
      body <- timed$value
      pack_seconds <- pack_seconds + timed$seconds
      roundtrip <- a_unpack_truth_plan(body, authority)
      roundtrip_equal[[i]] <- a_plan_scientific_equal(roundtrip, plan, authority)
    } else {
      timed <- a_elapsed(body_provider(i, registry, authority, layout))
      body <- timed$value
      pack_seconds <- pack_seconds + timed$seconds
      a_assert(length(body) == layout$body_bytes, "Synthetic packed body size differs.")
      plan_bytes[[i]] <- NA_real_
      roundtrip_equal[[i]] <- TRUE
    }
    checksum <- a_adler32(body)
    checksums[[i]] <- checksum
    timed <- a_elapsed({
      writeBin(body, con)
      writeBin(charToRaw(checksum), con)
    })
    write_seconds <- write_seconds + timed$seconds
  }
  if (complete && max_patterns == expected) {
    writeBin(charToRaw("SARADONE"), con)
    a_write_i32(con, expected)
    writeBin(charToRaw(a_adler32(charToRaw(paste0(checksums, collapse = "")))), con)
  }
  close(con)
  on.exit(NULL, add = FALSE)
  bstar_keys <- if (is.null(body_provider)) arch_bstar_finalize(bstar) else character()
  list(
    path = path,
    layout = layout,
    expected_patterns = expected,
    records_written = max_patterns,
    complete = complete && max_patterns == expected,
    file_bytes = as.numeric(file.info(path)$size),
    plan_bytes = plan_bytes,
    packed_body_bytes = layout$body_bytes,
    build_seconds = build_seconds,
    pack_seconds = pack_seconds,
    write_seconds = write_seconds,
    roundtrip_all_equal = all(roundtrip_equal),
    bstar_keys = bstar_keys,
    bstar_members = lapply(bstar_keys, arch_member_key_decode),
    bstar_peak_pending_bytes = if (is.null(body_provider)) {
      bstar$peak_pending_bytes
    } else 0,
    bstar_flush_count = if (is.null(body_provider)) bstar$flush_count else 0L
  )
}

a_open_packed_store <- function(path, registry, authority,
                                verify_all_records = TRUE) {
  con <- file(path, open = "rb")
  magic <- rawToChar(readBin(con, "raw", n = 8L))
  if (!identical(magic, "SARATP01")) {
    close(con)
    a_stop("Packed store has invalid or missing header.")
  }
  metadata <- a_read_i32(con, 7L)
  names(metadata) <- c(
    "version", "taxa", "primitive", "patterns", "key_bytes",
    "state_bytes", "record_bytes"
  )
  layout <- a_truth_layout(authority)
  expected_metadata <- as.integer(c(
    version = 1L, taxa = layout$taxa, primitive = layout$primitive,
    patterns = length(registry$pattern_ids), key_bytes = layout$key_bytes,
    state_bytes = layout$state_bytes, record_bytes = layout$record_bytes
  ))
  names(expected_metadata) <- names(metadata)
  if (!identical(metadata, expected_metadata)) {
    close(con)
    a_stop("Packed store metadata does not match registry/authority.")
  }
  expected_size <- layout$header_bytes +
    length(registry$pattern_ids) * layout$record_bytes + layout$footer_bytes
  actual_size <- as.numeric(file.info(path)$size)
  if (!identical(actual_size, as.numeric(expected_size))) {
    close(con)
    a_stop("Packed store is incomplete or has trailing data.")
  }
  seek(con, where = expected_size - layout$footer_bytes, origin = "start", rw = "read")
  footer_magic <- rawToChar(readBin(con, "raw", n = 8L))
  footer_count <- a_read_i32(con, 1L)
  footer_checksum <- rawToChar(readBin(con, "raw", n = 8L))
  if (!identical(footer_magic, "SARADONE") ||
      !identical(footer_count, as.integer(length(registry$pattern_ids)))) {
    close(con)
    a_stop("Packed store completion footer is absent or invalid.")
  }
  record_checksums <- character(length(registry$pattern_ids))
  for (i in seq_along(record_checksums)) {
    offset <- layout$header_bytes + (i - 1L) * layout$record_bytes +
      layout$body_bytes
    seek(con, where = offset, origin = "start", rw = "read")
    record_checksums[[i]] <- rawToChar(readBin(con, "raw", n = 8L))
  }
  observed_footer <- a_adler32(charToRaw(paste0(record_checksums, collapse = "")))
  if (!identical(observed_footer, footer_checksum)) {
    close(con)
    a_stop("Packed store footer checksum differs.")
  }
  e <- new.env(parent = emptyenv())
  e$con <- con
  e$path <- path
  e$registry <- registry
  e$authority <- authority
  e$layout <- layout
  e$expected_checksums <- record_checksums
  e$record_reads <- 0L
  e$bytes_read <- 0
  e$read_seconds <- 0
  e$decode_seconds <- 0
  e$closed <- FALSE
  e$get_body <- function(pattern_id) {
    if (e$closed) a_stop("Packed store is closed.")
    index <- match(pattern_id, e$registry$pattern_ids)
    if (is.na(index)) a_stop(sprintf("Unknown packed-store pattern: %s", pattern_id))
    offset <- e$layout$header_bytes + (index - 1L) * e$layout$record_bytes
    timed <- a_elapsed({
      seek(e$con, where = offset, origin = "start", rw = "read")
      body <- readBin(e$con, "raw", n = e$layout$body_bytes)
      checksum <- rawToChar(readBin(e$con, "raw", n = 8L))
      list(body = body, checksum = checksum)
    })
    e$read_seconds <- e$read_seconds + timed$seconds
    body <- timed$value$body
    checksum <- timed$value$checksum
    if (length(body) != e$layout$body_bytes ||
        !identical(checksum, e$expected_checksums[[index]]) ||
        !identical(a_adler32(body), checksum)) {
      a_stop(sprintf("Packed truth-plan record %s failed checksum.", pattern_id))
    }
    e$record_reads <- e$record_reads + 1L
    e$bytes_read <- e$bytes_read + e$layout$record_bytes
    body
  }
  e$decode_body <- function(body) a_unpack_truth_plan(body, e$authority)
  e$get <- function(pattern_id) {
    body <- e$get_body(pattern_id)
    timed <- a_elapsed(e$decode_body(body))
    e$decode_seconds <- e$decode_seconds + timed$seconds
    timed$value
  }
  e$stats <- function() list(
    strategy = "packed_disk",
    record_reads = e$record_reads,
    bytes_read = e$bytes_read,
    read_seconds = e$read_seconds,
    decode_seconds = e$decode_seconds,
    file_bytes = actual_size,
    index_bytes = as.numeric(object.size(list(
      pattern_ids = e$registry$pattern_ids,
      exact_pattern_keys = e$registry$exact_pattern_keys,
      checksums = e$expected_checksums
    ))),
    packed_body_bytes = e$layout$body_bytes,
    complete_footer_verified = TRUE
  )
  e$close <- function() {
    if (!e$closed) close(e$con)
    e$closed <- TRUE
    invisible(TRUE)
  }
  class(e) <- c("arch000a_packed_disk_store", "environment")
  if (verify_all_records) {
    tryCatch({
      for (pattern_id in registry$pattern_ids) e$get_body(pattern_id)
    }, error = function(error) {
      e$close()
      stop(error)
    })
  }
  e
}

a_corrupt_copy_byte <- function(source, target, offset) {
  bytes <- readBin(source, "raw", n = file.info(source)$size)
  a_assert(offset >= 1L && offset <= length(bytes), "Corruption offset outside file.")
  bytes[[offset]] <- as.raw(bitwXor(as.integer(bytes[[offset]]), 1L))
  writeBin(bytes, target)
  invisible(target)
}
