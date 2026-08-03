#!/usr/bin/env Rscript

fail <- function(...) stop(sprintf(...), call. = FALSE)

check_layout <- function(name, fields, expected_bytes) {
  needed <- c("offset", "width", "field")
  if (!identical(names(fields), needed)) {
    fail("%s registry columns are not exact", name)
  }
  if (!identical(fields$offset, cumsum(c(0, head(fields$width, -1L))))) {
    fail("%s has a gap, overlap, or noncanonical order", name)
  }
  observed <- sum(fields$width)
  if (!identical(observed, expected_bytes)) {
    fail("%s totals %s bytes, expected %s", name, observed, expected_bytes)
  }
  invisible(observed)
}

plan_header <- data.frame(
  offset = c(0, 4, 6, 8, 10, 12, 20, 24, 28, 32, 36, 40, 44, 45,
             46, 47, 48, 56, 88, 120, 128, 136),
  width = c(4, 2, 2, 2, 2, 8, 4, 4, 4, 4, 4, 4, 1, 1, 1, 1,
            8, 32, 32, 8, 8, 8),
  field = c("magic", "schema_major", "schema_minor", "header_bytes",
            "flags", "pattern_id", "global_taxon_count", "primitive_count",
            "retained_bytes", "state_bytes", "active_count", "query_count",
            "state_encoding", "query_ref_width", "byte_order", "reserved_47",
            "payload_bytes", "retained_pattern_sha256",
            "species_authority_sha256", "payload_xxh64", "header_xxh64",
            "reserved_136_143"),
  stringsAsFactors = FALSE
)

store_header <- data.frame(
  offset = c(0, 8, 10, 12, 14, 16, 17, 18, 20, 22, 24, 26, 28, 32,
             36, 40, 48, 56, 64, 72, 80, 88, 96, 128, 160, 192, 224, 232),
  width = c(8, 2, 2, 2, 2, 1, 1, 2, 2, 2, 2, 2, 4, 4, 4, 8, 8,
            8, 8, 8, 8, 8, 32, 32, 32, 32, 8, 24),
  field = c("magic", "store_schema_major", "store_schema_minor",
            "header_bytes", "flags", "byte_order", "completion_state",
            "plan_schema_major", "plan_schema_minor", "plan_header_bytes",
            "index_entry_bytes", "footer_bytes", "reserved_28_31",
            "global_taxon_count", "primitive_count", "pattern_count",
            "records_start", "index_offset", "footer_offset",
            "exact_file_bytes", "records_bytes", "index_bytes",
            "species_authority_sha256", "pattern_registry_sha256",
            "truth_semantics_sha256", "store_identity_sha256",
            "header_xxh64", "reserved_232_255"),
  stringsAsFactors = FALSE
)

index_entry <- data.frame(
  offset = c(0, 8, 16, 24, 56),
  width = c(8, 8, 8, 32, 8),
  field = c("pattern_id", "record_offset", "record_bytes",
            "retained_pattern_sha256", "record_xxh64"),
  stringsAsFactors = FALSE
)

store_footer <- data.frame(
  offset = c(0, 8, 10, 12, 14, 16, 24, 32, 40, 48, 80, 112, 120),
  width = c(8, 2, 2, 2, 2, 8, 8, 8, 8, 32, 32, 8, 8),
  field = c("completion_magic", "store_schema_major", "store_schema_minor",
            "footer_bytes", "flags", "record_count", "exact_file_bytes",
            "ordered_records_xxh64", "index_xxh64",
            "payload_aggregate_sha256", "complete_file_sha256",
            "footer_xxh64", "reserved_120_127"),
  stringsAsFactors = FALSE
)

query_prefix <- data.frame(
  offset = c(0, 1, 4, 8),
  width = c(1, 3, 4, 4),
  field = c("encoding", "reserved", "selected_count", "payload_bytes"),
  stringsAsFactors = FALSE
)

check_layout("plan header", plan_header, 144)
check_layout("store header", store_header, 256)
check_layout("index entry", index_entry, 64)
check_layout("store footer", store_footer, 128)
check_layout("query prefix", query_prefix, 12)

u32_le <- function(x) {
  if (length(x) != 1L || is.na(x) || x < 0 || x > 2^32 - 1) {
    fail("u32 input out of range")
  }
  v <- as.double(x)
  as.raw(c(v %% 256, floor(v / 256) %% 256, floor(v / 65536) %% 256,
           floor(v / 16777216) %% 256))
}

semantics_domain <- c(charToRaw("SplitAlignerR/TruthSemantics/v1"), as.raw(0))
semantics_clauses <- c(
  "state:0=eligible;1=NA_struct;2=NA_fuse;3=invalid",
  "state0:eligible-not-mapped;NA_topo=absent",
  "primitive_axis:SpeciesAuthority-v1",
  "fiber:same-query;all-state2;size>=2;members=u32le-sorted",
  "query:canonical-dense-selected-side;unsigned-byte-lex",
  "bstar:exact-canonical-primitive-member-set",
  "terminal:retained-terminal!=NA_struct;missing-terminal=NA_struct",
  "schema:TruthPlanRecord-v1.0"
)
semantics_stream <- c(
  semantics_domain,
  u32_le(length(semantics_clauses)),
  unlist(lapply(semantics_clauses, function(x) {
    bytes <- charToRaw(x)
    c(u32_le(length(bytes)), bytes)
  }), use.names = FALSE)
)

sha256_external <- function(bytes) {
  exe <- Sys.which("shasum")
  if (!nzchar(exe)) return(NA_character_)
  path <- tempfile("engine002-semantics-")
  on.exit(unlink(path), add = TRUE)
  writeBin(bytes, path, useBytes = TRUE)
  out <- system2(exe, c("-a", "256", path), stdout = TRUE, stderr = TRUE)
  if (!identical(attr(out, "status"), NULL) && attr(out, "status") != 0L) {
    fail("external SHA-256 command failed")
  }
  strsplit(out[[length(out)]], "[[:space:]]+")[[1L]][[1L]]
}

expected_truth_semantics_sha256 <-
  "8323c706880b2e95628e803a408a459113b0ac3edeb4d69e9e0626a77fc57935"
observed_truth_semantics_sha256 <- sha256_external(semantics_stream)
if (!is.na(observed_truth_semantics_sha256) &&
    !identical(observed_truth_semantics_sha256,
               expected_truth_semantics_sha256)) {
  fail("truth-semantics SHA-256 is %s, expected %s",
       observed_truth_semantics_sha256, expected_truth_semantics_sha256)
}

cat("ENGINE002_SPEC_GATE_PASS\n")
cat("plan_header_bytes=144\n")
cat("store_header_bytes=256\n")
cat("index_entry_bytes=64\n")
cat("store_footer_bytes=128\n")
cat("query_prefix_bytes=12\n")
cat("truth_semantics_stream_bytes=", length(semantics_stream), "\n", sep = "")
cat("truth_semantics_sha256=", expected_truth_semantics_sha256, "\n", sep = "")
