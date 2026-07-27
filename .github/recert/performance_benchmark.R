args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2L) {
  stop("usage: performance_benchmark.R SOURCE_ROOT OUTPUT_DIR", call. = FALSE)
}

source_root <- normalizePath(args[[1L]], mustWork = TRUE)
output_dir <- args[[2L]]
if (dir.exists(output_dir)) {
  stop("refusing to overwrite existing benchmark output directory", call. = FALSE)
}
dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)
suppressPackageStartupMessages(library(SplitAlignerR))

balanced_newick <- function(labels, root = TRUE) {
  if (length(labels) == 1L) {
    return(paste0(labels, ":1"))
  }
  midpoint <- length(labels) %/% 2L
  left <- balanced_newick(labels[seq_len(midpoint)], root = FALSE)
  right <- balanced_newick(labels[(midpoint + 1L):length(labels)], root = FALSE)
  node <- paste0("(", left, ",", right, "):1")
  if (root) paste0(node, ";") else node
}

timed <- function(expression) {
  timing <- system.time(force(expression), gcFirst = TRUE)
  c(
    wall = unname(timing[["elapsed"]]),
    user = unname(timing[["user.self"]]),
    system = unname(timing[["sys.self"]])
  )
}

taxa_sizes <- c(50L, 200L, 302L, 500L)
repetitions <- 3L
io_inner_iterations <- 200L
source_commit <- system2(
  "git", c("-C", shQuote(source_root), "rev-parse", "HEAD"),
  stdout = TRUE, stderr = TRUE
)
compiler <- system2(
  "R", c("CMD", "config", "CXX17"), stdout = TRUE, stderr = TRUE
)
hardware <- c(
  sprintf("runner_name=%s", Sys.getenv("RUNNER_NAME", "NOT_AVAILABLE")),
  sprintf("runner_os=%s", Sys.getenv("RUNNER_OS", Sys.info()[["sysname"]])),
  sprintf("runner_arch=%s", Sys.getenv("RUNNER_ARCH", Sys.info()[["machine"]])),
  sprintf("logical_cores=%s", parallel::detectCores(logical = TRUE))
)
cpu_model <- tryCatch(
  {
    if (identical(Sys.info()[["sysname"]], "Darwin")) {
      value <- suppressWarnings(system2(
        "sysctl", c("-n", "machdep.cpu.brand_string"),
        stdout = TRUE, stderr = TRUE
      ))
      if (!is.null(attr(value, "status"))) "UNAVAILABLE" else
        paste(value, collapse = " ")
    } else if (identical(Sys.info()[["sysname"]], "Linux") &&
               file.exists("/proc/cpuinfo")) {
      line <- grep(
        "^model name\\s*:", readLines("/proc/cpuinfo", warn = FALSE),
        value = TRUE
      )
      if (length(line)) sub("^[^:]+:\\s*", "", line[[1L]]) else "UNKNOWN"
    } else {
      Sys.getenv("PROCESSOR_IDENTIFIER", "UNKNOWN")
    }
  },
  error = function(e) paste("UNAVAILABLE", conditionMessage(e))
)
metadata <- c(
  "benchmark_id: balanced-projection-v1",
  sprintf("source_commit: %s", paste(source_commit, collapse = " ")),
  "tree_topology: deterministic recursively balanced binary Newick",
  "gene_count: 3",
  "gene_patterns: full concordant; deterministic 10-percent missing; full reversed-label topology",
  sprintf("taxa_sizes: %s", paste(taxa_sizes, collapse = ",")),
  sprintf("repetitions: %d", repetitions),
  sprintf("io_inner_iterations_per_repetition: %d", io_inner_iterations),
  paste0("hardware: ", paste(hardware, collapse = "; ")),
  sprintf("cpu_model: %s", cpu_model),
  sprintf("os: %s", paste(Sys.info()[c("sysname", "release", "machine")], collapse = " ")),
  sprintf("R: %s", R.version.string),
  sprintf("R_platform: %s", R.version$platform),
  sprintf("compiler: %s", paste(compiler, collapse = " ")),
  "timing_scope: input generation excluded; write, read, and align computation timed separately",
  sprintf("started_utc: %s", format(Sys.time(), tz = "UTC", usetz = TRUE))
)
writeLines(metadata, file.path(output_dir, "METADATA.txt"), useBytes = TRUE)

rows <- list()
for (taxa in taxa_sizes) {
  labels <- sprintf("t%06d", seq_len(taxa))
  species <- balanced_newick(labels)
  missing_indices <- seq.int(10L, taxa, by = 10L)
  retained <- labels[-missing_indices]
  genes <- c(
    full_concordant = species,
    missing_10_percent = balanced_newick(retained),
    full_reversed = balanced_newick(rev(labels))
  )
  payload <- unname(c(species, genes))

  warmup <- align_branches(
    species, genes, mode = "free", gene_ids = names(genes)
  )
  stopifnot(
    nrow(warmup$state_matrix) == length(genes),
    all(is.na(warmup$numeric_matrix) | is.finite(warmup$numeric_matrix))
  )

  for (repetition in seq_len(repetitions)) {
    path <- tempfile(pattern = sprintf("splitalignerr-%d-", taxa), fileext = ".trees")
    write_timing <- timed(for (i in seq_len(io_inner_iterations)) {
      writeLines(payload, path, useBytes = TRUE)
    })
    read_value <- NULL
    read_timing <- timed(for (i in seq_len(io_inner_iterations)) {
      read_value <- readLines(path, warn = FALSE, encoding = "UTF-8")
    })
    stopifnot(identical(read_value, payload))
    computation <- NULL
    compute_timing <- timed(
      computation <- align_branches(
        species, genes, mode = "free", gene_ids = names(genes)
      )
    )
    stopifnot(nrow(computation$state_matrix) == length(genes))
    unlink(path)

    rows[[length(rows) + 1L]] <- data.frame(
      taxa = taxa,
      gene_count = length(genes),
      missing_gene_taxa = length(retained),
      repetition = repetition,
      io_inner_iterations = io_inner_iterations,
      input_bytes = sum(nchar(payload, type = "bytes")) + length(payload),
      write_wall_seconds_per_operation =
        write_timing[["wall"]] / io_inner_iterations,
      write_cpu_seconds_per_operation =
        (write_timing[["user"]] + write_timing[["system"]]) /
        io_inner_iterations,
      read_wall_seconds_per_operation =
        read_timing[["wall"]] / io_inner_iterations,
      read_cpu_seconds_per_operation =
        (read_timing[["user"]] + read_timing[["system"]]) /
        io_inner_iterations,
      compute_wall_seconds = compute_timing[["wall"]],
      compute_cpu_seconds = compute_timing[["user"]] + compute_timing[["system"]],
      stringsAsFactors = FALSE
    )
  }
}

timings <- do.call(rbind, rows)
utils::write.table(
  timings,
  file = file.path(output_dir, "TIMINGS.tsv"),
  sep = "\t", quote = FALSE, row.names = FALSE
)
summary_rows <- do.call(rbind, lapply(split(timings, timings$taxa), function(x) {
  io_wall <- x$write_wall_seconds_per_operation +
    x$read_wall_seconds_per_operation
  data.frame(
    taxa = x$taxa[[1L]],
    repetitions = nrow(x),
    median_io_wall_seconds = median(io_wall),
    median_compute_wall_seconds = median(x$compute_wall_seconds),
    compute_to_io_wall_ratio = median(x$compute_wall_seconds) / median(io_wall),
    stringsAsFactors = FALSE
  )
}))
rownames(summary_rows) <- NULL
summary_rows$taxa_ratio_from_smallest <-
  summary_rows$taxa / summary_rows$taxa[[1L]]
summary_rows$compute_ratio_from_smallest <-
  summary_rows$median_compute_wall_seconds /
  summary_rows$median_compute_wall_seconds[[1L]]
summary_rows$empirical_growth_exponent_from_smallest <- c(
  NA_real_,
  log(summary_rows$compute_ratio_from_smallest[-1L]) /
    log(summary_rows$taxa_ratio_from_smallest[-1L])
)
utils::write.table(
  summary_rows,
  file = file.path(output_dir, "SUMMARY.tsv"),
  sep = "\t", quote = FALSE, row.names = FALSE
)
writeLines(
  c(
    "measurement_status: PASS",
    "interpretation: measured align computation dominates measured text-file I/O for this benchmark; no extrapolated timings are reported",
    "scope: evidence only; no performance optimization was performed",
    sprintf("finished_utc: %s", format(Sys.time(), tz = "UTC", usetz = TRUE))
  ),
  file.path(output_dir, "VERDICT.txt"),
  useBytes = TRUE
)
if (any(
  summary_rows$median_compute_wall_seconds <=
    summary_rows$median_io_wall_seconds
)) {
  stop("measured alignment computation did not dominate measured I/O")
}
cat("performance_benchmark: PASS\n")
