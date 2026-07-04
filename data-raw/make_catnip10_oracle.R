# Build data/catnip10_oracle.rda from the Catnip10 benchmark oracle outputs.
#
# Source of truth: the frozen SplitAligner benchmark package. Run this script
# from the SplitAlignerR package root (working directory) whenever the
# benchmark outputs change:
#     Rscript data-raw/make_catnip10_oracle.R
#
# The unrooted axis is used because it is the manuscript-facing primitive
# branch-coordinate system.

bench <- Sys.getenv(
  "CATNIP10_BENCHMARK_DIR",
  unset = NA_character_
)

if (is.na(bench) || !nzchar(bench)) {
  stop(
    "Please set CATNIP10_BENCHMARK_DIR to the benchmark output directory.",
    call. = FALSE
  )
}

read_tsv <- function(path) {
  utils::read.delim(
    path,
    header = TRUE, sep = "\t", quote = "",
    check.names = FALSE, colClasses = "character",
    stringsAsFactors = FALSE
  )
}

read_matrix <- function(path) {
  df <- read_tsv(path)
  names(df)[1] <- "gene_id"
  df
}

load_regime <- function(dir, deletion_order) {
  u <- file.path(dir, "benchmark_unrooted")
  list(
    matrix = read_matrix(file.path(u, "oracle_gene_by_original_branch_matrix.tsv")),
    status_long = read_tsv(file.path(u, "oracle_cell_status_long.tsv")),
    fusion_groups = read_tsv(file.path(u, "oracle_fusion_groups.tsv")),
    deletion_order = deletion_order
  )
}

global_dir <- file.path(bench, "t10_global_deletion")
local_dir <- file.path(bench, "t8_to_t3_local_deletion")

catnip10_oracle <- list(
  species_tree = readLines(
    file.path(global_dir, "benchmark_unrooted", "benchmark.species_tree.nwk"),
    warn = FALSE
  )[1],
  branch_map = read_tsv(file.path(global_dir, "branch_label_map.tsv")),
  global = load_regime(global_dir, c("t10", "t1", "t8", "t7", "t4", "t9", "t5")),
  local  = load_regime(local_dir,  c("t8", "t7", "t4", "t9", "t5", "t2", "t3"))
)

# sanity checks: 8 rows (step0 + 7) and 17 primitive coordinates + gene_id
stopifnot(
  nrow(catnip10_oracle$global$matrix) == 8L,
  nrow(catnip10_oracle$local$matrix) == 8L,
  ncol(catnip10_oracle$global$matrix) == 18L,
  ncol(catnip10_oracle$local$matrix) == 18L
)

save(
  catnip10_oracle,
  file = file.path("data", "catnip10_oracle.rda"),
  compress = "bzip2", version = 3
)

cat("Wrote data/catnip10_oracle.rda\n")
