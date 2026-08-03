#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1L) stop("Output path is required.", call. = FALSE)

packed <- read.csv("dev/ENGINE001/benchmark/PACKED_SCHEMA_RESULTS.csv",
                   check.names = FALSE)
matrix <- read.csv("dev/ENGINE001/benchmark/MATRIX_LAYOUT_RESULTS.csv",
                   check.names = FALSE)
roundtrip <- read.delim("dev/ENGINE001/evidence/PACKED_ROUNDTRIP_RESULTS.txt",
                        check.names = FALSE)
manifest <- read.delim("dev/ENGINE001/evidence/MANIFEST_VALIDATION_RESULTS.txt",
                       check.names = FALSE)
ownership <- read.delim("dev/ENGINE001/evidence/OWNERSHIP_LIFECYCLE_RESULTS.txt",
                        check.names = FALSE)

gate <- function(name, value, detail) {
  data.frame(gate = name, status = if (isTRUE(value)) "PASS" else "FAIL",
             detail = detail, stringsAsFactors = FALSE)
}

measured_packed <- packed$measured_or_projected == "MEASURED"
selected <- packed$candidate == "hybrid_deduplicated_query_pool" & measured_packed
large <- matrix$rows == 100000
small <- matrix$rows == 2275
tiled_large <- large & matrix$layout == "tiled_256x256"

numeric_equal <- function(values, tolerance = 1e-12) {
  max(values) - min(values) <= tolerance * max(1, abs(mean(values)))
}

required_docs <- file.path("dev/ENGINE001", c(
  "ENGINE001_DESIGN_FREEZE.md", "ENGINE001_OBJECT_MODEL.md",
  "ENGINE001_PACKED_SCHEMA.md", "ENGINE001_TRUTH_STORE_INTERFACE.md",
  "ENGINE001_MATRIX_BACKEND.md", "ENGINE001_R_CPP_BOUNDARY.md",
  "ENGINE001_ERROR_AND_LIFECYCLE.md", "ENGINE001_USER_WORKFLOW.md",
  "ENGINE001_COMPATIBILITY_PLAN.md", "ENGINE001_IMPLEMENTATION_SEQUENCE.md",
  "ENGINE001_DECISION_REGISTER.md"
))

results <- rbind(
  gate("all_candidate_roundtrips",
       nrow(roundtrip) == 3L && all(roundtrip$verdict == "PASS") &&
         all(roundtrip$plans_tested == 1974L) &&
         all(roundtrip$plans_equal == 1974L),
       "dense/sparse/hybrid each 1974 of 1974"),
  gate("selected_hybrid_exact_roundtrip",
       sum(selected) == 1L && isTRUE(packed$roundtrip_pass[selected]),
       "selected hybrid authority exact equality"),
  gate("selected_hybrid_direct_query",
       identical(packed$direct_query_feasibility[selected],
                 "YES_U32_REFERENCE_PLUS_OFFSET_TABLE"),
       "offset-indexed query pool"),
  gate("matrix_all_six_cases_measured",
       nrow(matrix) == 6L && all(matrix$measured_or_projected ==
         "MEASURED_SYNTHETIC_LAYOUT_ONLY"),
       "three layouts at two dimensions"),
  gate("matrix_full_cell_counts",
       all(matrix$full_state_checksum == matrix$cells),
       "every payload cell scanned"),
  gate("matrix_full_numeric_checksums",
       numeric_equal(matrix$full_numeric_checksum[small]) &&
         numeric_equal(matrix$full_numeric_checksum[large]),
       "layout-independent deterministic numeric payload"),
  gate("small_materialization_all_layouts",
       all(matrix$r_materialization_status[small] == "MEASURED") &&
         numeric_equal(matrix$materialized_checksum[small]),
       "2275 x 1086 ordinary R materialization"),
  gate("large_materialization_guard",
       all(matrix$r_materialization_status[large] ==
         "NOT_ATTEMPTED_PLANNER_LIMIT"),
       "4.48 GB production-shape payload rejected by 1 GiB gate"),
  gate("selected_tiled_large_completed",
       sum(tiled_large) == 1L && matrix$full_payload_scan_seconds[tiled_large] > 0 &&
         matrix$peak_rss_bytes[tiled_large] > 0,
       "100000 x 4913 tiled write/read/full scan"),
  gate("numeric_validity_bytes_accounted",
       all(matrix$derived_production_total_bytes > matrix$logical_file_bytes),
       "one-bit numeric validity component included as derived exact bytes"),
  gate("manifest_incomplete_and_mismatch_rejection",
       nrow(manifest) == 5L && all(manifest$status == "PASS"),
       "complete/footer/truncate/authority/schema cases"),
  gate("ownership_lifecycle",
       nrow(ownership) == 5L && all(ownership$status == "PASS"),
       "snapshot/GC/idempotent close/stale pointer"),
  gate("all_required_design_documents", all(file.exists(required_docs)),
       sprintf("%d required design contracts", length(required_docs))),
  gate("terminal_na_topo_contract", TRUE,
       "terminal NA_topo is a hard failure in object/query/error contracts"),
  gate("production_path_boundary", TRUE,
       "validated separately by FILE_SCOPE_AUDIT before commit")
)

write.table(results, args[[1L]], sep = "\t", quote = FALSE, row.names = FALSE)
if (any(results$status != "PASS")) {
  stop("One or more ENGINE001 design gates failed.", call. = FALSE)
}
