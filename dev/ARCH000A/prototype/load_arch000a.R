## Load all ARCH000A development-only prototypes from the repository root.

source("dev/ARCH000/prototype/arch000_common.R")
source("dev/ARCH000A/prototype/compact_pattern_registry.R")
source("dev/ARCH000A/prototype/recompute_truth_store.R")
source("dev/ARCH000A/prototype/bounded_lru_truth_store.R")
source("dev/ARCH000A/prototype/packed_disk_truth_store.R")
source("dev/ARCH000A/prototype/adaptive_truth_store_selector.R")
source("dev/ARCH000A/prototype/stress_workload_generator.R")
source("dev/ARCH000A/prototype/streaming_truth_store_engine.R")
source("dev/ARCH000A/prototype/bstar_churn_stress.R")

a_as_records <- function(values) {
  ids <- names(values)
  if (is.null(ids)) ids <- sprintf("gene_%06d", seq_along(values))
  paste0(ids, " ", unname(values))
}
