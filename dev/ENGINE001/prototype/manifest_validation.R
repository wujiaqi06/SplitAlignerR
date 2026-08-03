## ENGINE001 isolated completion/integrity validation prototype.

source("dev/ENGINE001/prototype/packed_schema_comparison.R")

e1_hash_raw <- function(value, algorithm = "xxhash64") {
  digest::digest(value, algo = algorithm, serialize = FALSE)
}

e1_hex_to_raw <- function(value) {
  if (length(value) != 1L || nchar(value) %% 2L) {
    stop("Fingerprint must be one even-width hexadecimal string.", call. = FALSE)
  }
  starts <- seq.int(1L, nchar(value), by = 2L)
  as.raw(strtoi(substring(value, starts, starts + 1L), base = 16L))
}

e1_u64 <- function(value) {
  value <- as.double(value)
  if (length(value) != 1L || is.na(value) || value < 0 ||
      value > 2^53 - 1 || value != floor(value)) {
    stop("Prototype u64 value is outside exact R range.", call. = FALSE)
  }
  c(e1_u32(value %% 2^32), e1_u32(floor(value / 2^32)))
}

e1_read_u64 <- function(bytes, offset) {
  values <- e1_read_u32(bytes, offset, 2L)
  list(value = values$value[[1L]] + values$value[[2L]] * 2^32,
       next_offset = values$next_offset)
}

e1_manifest_header <- function(schema, species_fingerprint, payload) {
  fingerprint <- e1_hex_to_raw(species_fingerprint)
  if (length(fingerprint) != 32L) {
    stop("Species fingerprint must be SHA-256 width.", call. = FALSE)
  }
  payload_hash <- charToRaw(e1_hash_raw(payload))
  core <- c(charToRaw("SARMAN01"), e1_u32(schema), e1_u64(length(payload)),
            fingerprint, payload_hash)
  c(core, charToRaw(e1_hash_raw(core)))
}

e1_manifest_footer <- function(payload, total_without_footer) {
  core <- c(charToRaw("SARDONE1"), e1_u64(total_without_footer + 32L),
            charToRaw(e1_hash_raw(payload)))
  stopifnot(length(core) == 32L)
  core
}

e1_write_manifest_store <- function(path, payload, species_fingerprint,
                                    schema = 1L, complete = TRUE) {
  header <- e1_manifest_header(schema, species_fingerprint, payload)
  footer <- e1_manifest_footer(payload, length(header) + length(payload))
  con <- file(path, open = "wb")
  on.exit(close(con), add = TRUE)
  writeBin(header, con)
  writeBin(payload, con)
  if (complete) writeBin(footer, con)
  invisible(path)
}

e1_validate_manifest_store <- function(path, expected_species_fingerprint,
                                       expected_schema = 1L) {
  bytes <- readBin(path, "raw", n = file.info(path)$size)
  header_bytes <- 8L + 4L + 8L + 32L + 16L + 16L
  footer_bytes <- 32L
  if (length(bytes) < header_bytes + footer_bytes) {
    stop("[ENGINE_INCOMPLETE_RUN] store is too short for header and footer.",
         call. = FALSE)
  }
  if (rawToChar(bytes[1:8]) != "SARMAN01") {
    stop("[ENGINE_SCHEMA_MISMATCH] store magic differs.", call. = FALSE)
  }
  schema <- e1_read_u32(bytes, 9L)$value[[1L]]
  if (schema != expected_schema) {
    stop("[ENGINE_SCHEMA_MISMATCH] schema version differs.", call. = FALSE)
  }
  payload_length <- e1_read_u64(bytes, 13L)$value
  fingerprint <- paste(sprintf("%02x", as.integer(bytes[21:52])), collapse = "")
  if (!identical(fingerprint, expected_species_fingerprint)) {
    stop("[ENGINE_AUTHORITY_MISMATCH] species fingerprint differs.",
         call. = FALSE)
  }
  payload_hash <- rawToChar(bytes[53:68])
  header_hash <- rawToChar(bytes[69:84])
  if (!identical(header_hash, e1_hash_raw(bytes[1:68]))) {
    stop("[ENGINE_STORE_CORRUPT] header checksum differs.", call. = FALSE)
  }
  expected_total <- header_bytes + payload_length + footer_bytes
  if (length(bytes) != expected_total) {
    stop("[ENGINE_INCOMPLETE_RUN] exact file length differs.", call. = FALSE)
  }
  payload <- bytes[header_bytes + seq_len(payload_length)]
  footer <- bytes[header_bytes + payload_length + seq_len(footer_bytes)]
  if (rawToChar(footer[1:8]) != "SARDONE1") {
    stop("[ENGINE_INCOMPLETE_RUN] completion footer is missing.", call. = FALSE)
  }
  footer_total <- e1_read_u64(footer, 9L)$value
  footer_hash <- rawToChar(footer[17:32])
  observed_hash <- e1_hash_raw(payload)
  if (footer_total != length(bytes) || !identical(payload_hash, observed_hash) ||
      !identical(footer_hash, observed_hash)) {
    stop("[ENGINE_STORE_CORRUPT] payload/footer validation failed.",
         call. = FALSE)
  }
  list(status = "VALIDATED", schema = schema,
       species_fingerprint = fingerprint,
       payload_bytes = payload_length, checksum = observed_hash)
}

e1_capture_validation <- function(name, expression, expected) {
  observed <- tryCatch({
    force(expression)
    "ACCEPTED"
  }, error = function(condition) conditionMessage(condition))
  passed <- if (expected == "ACCEPTED") {
    identical(observed, "ACCEPTED")
  } else {
    startsWith(observed, expected)
  }
  data.frame(case = name, expected = expected, observed = observed,
             status = if (passed) "PASS" else "FAIL",
             stringsAsFactors = FALSE)
}

e1_run_manifest_validation <- function(output_path) {
  root <- tempfile("engine001-manifest-")
  dir.create(root)
  on.exit(unlink(root, recursive = TRUE, force = TRUE), add = TRUE)
  species <- digest::digest(charToRaw("species-authority"), algo = "sha256",
                            serialize = FALSE)
  wrong_species <- digest::digest(charToRaw("wrong-authority"), algo = "sha256",
                                  serialize = FALSE)
  payload <- as.raw((seq_len(65537L) - 1L) %% 251L)
  complete <- file.path(root, "complete.bin")
  no_footer <- file.path(root, "no-footer.bin")
  truncated <- file.path(root, "truncated.bin")
  e1_write_manifest_store(complete, payload, species, 1L, TRUE)
  e1_write_manifest_store(no_footer, payload, species, 1L, FALSE)
  bytes <- readBin(complete, "raw", n = file.info(complete)$size)
  writeBin(bytes[-seq.int(length(bytes) - 16L, length(bytes))], truncated)
  results <- rbind(
    e1_capture_validation(
      "complete_run_accepted",
      e1_validate_manifest_store(complete, species, 1L), "ACCEPTED"
    ),
    e1_capture_validation(
      "missing_footer_rejected",
      e1_validate_manifest_store(no_footer, species, 1L),
      "[ENGINE_INCOMPLETE_RUN]"
    ),
    e1_capture_validation(
      "truncated_matrix_rejected",
      e1_validate_manifest_store(truncated, species, 1L),
      "[ENGINE_INCOMPLETE_RUN]"
    ),
    e1_capture_validation(
      "wrong_species_fingerprint_rejected",
      e1_validate_manifest_store(complete, wrong_species, 1L),
      "[ENGINE_AUTHORITY_MISMATCH]"
    ),
    e1_capture_validation(
      "wrong_schema_rejected",
      e1_validate_manifest_store(complete, species, 2L),
      "[ENGINE_SCHEMA_MISMATCH]"
    )
  )
  write.table(results, output_path, sep = "\t", quote = FALSE, row.names = FALSE)
  if (any(results$status != "PASS")) {
    stop("ENGINE001 manifest validation failed.", call. = FALSE)
  }
  invisible(results)
}

if (sys.nframe() == 0L) {
  args <- commandArgs(trailingOnly = TRUE)
  if (length(args) != 1L) {
    stop("Usage: manifest_validation.R output.txt", call. = FALSE)
  }
  e1_run_manifest_validation(args[[1L]])
}
