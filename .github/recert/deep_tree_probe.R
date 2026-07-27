args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2L) {
  stop("usage: deep_tree_probe.R SOURCE_ROOT OUTPUT_DIR", call. = FALSE)
}
if (!requireNamespace("processx", quietly = TRUE)) {
  stop("deep-tree probe requires processx", call. = FALSE)
}

source_root <- normalizePath(args[[1L]], mustWork = TRUE)
output_dir <- args[[2L]]
if (dir.exists(output_dir)) {
  stop("refusing to overwrite existing deep-tree output directory", call. = FALSE)
}
dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)
case_script <- file.path(source_root, ".github", "recert", "deep_tree_case.R")

size_text <- Sys.getenv(
  "SPLITALIGNERR_DEEP_TREE_SIZES",
  "50,200,302,500,750,1000,1500,2000,3000,5000"
)
sizes <- suppressWarnings(as.integer(strsplit(size_text, ",", fixed = TRUE)[[1L]]))
if (!length(sizes) || anyNA(sizes) || any(sizes < 2L) || is.unsorted(sizes)) {
  stop("SPLITALIGNERR_DEEP_TREE_SIZES must be increasing integers >= 2")
}
timeout_seconds <- suppressWarnings(as.numeric(Sys.getenv(
  "SPLITALIGNERR_DEEP_TREE_TIMEOUT_SECONDS", "60"
)))
if (!is.finite(timeout_seconds) || timeout_seconds <= 0) {
  stop("SPLITALIGNERR_DEEP_TREE_TIMEOUT_SECONDS must be positive")
}

source_commit <- system2(
  "git", c("-C", shQuote(source_root), "rev-parse", "HEAD"),
  stdout = TRUE, stderr = TRUE
)
compiler <- system2(
  "R", c("CMD", "config", "CXX17"), stdout = TRUE, stderr = TRUE
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
  "probe_id: recursive-depth-comb-v1",
  sprintf("source_commit: %s", paste(source_commit, collapse = " ")),
  "generator: deterministic_left_comb_v1",
  "generator_definition: start=(t000001:1,t000002:1):1; append=(previous,tNNNNNN:1):1; terminate=;",
  sprintf("requested_sizes: %s", paste(sizes, collapse = ",")),
  sprintf("per_case_timeout_seconds: %s", timeout_seconds),
  sprintf("runner_os: %s", Sys.getenv("RUNNER_OS", Sys.info()[["sysname"]])),
  sprintf("runner_arch: %s", Sys.getenv("RUNNER_ARCH", Sys.info()[["machine"]])),
  sprintf("hardware_logical_cores: %s", parallel::detectCores(logical = TRUE)),
  sprintf("cpu_model: %s", cpu_model),
  sprintf("os: %s", paste(Sys.info()[c("sysname", "release", "machine")], collapse = " ")),
  sprintf("R: %s", R.version.string),
  sprintf("R_platform: %s", R.version$platform),
  sprintf("compiler: %s", paste(compiler, collapse = " ")),
  sprintf("started_utc: %s", format(Sys.time(), tz = "UTC", usetz = TRUE))
)
writeLines(metadata, file.path(output_dir, "METADATA.txt"), useBytes = TRUE)

operations <- c("validate_species_tree", "align_branches")
rows <- list()
hard_failure <- FALSE
for (operation in operations) {
  for (taxa in sizes) {
    label <- sprintf("%s_taxa_%06d", operation, taxa)
    result <- processx::run(
      command = file.path(R.home("bin"), "Rscript"),
      args = c(case_script, operation, as.character(taxa)),
      error_on_status = FALSE,
      echo = FALSE,
      timeout = timeout_seconds,
      cleanup_tree = TRUE,
      windows_verbatim_args = FALSE
    )
    stdout_file <- file.path(output_dir, paste0(label, ".stdout.txt"))
    stderr_file <- file.path(output_dir, paste0(label, ".stderr.txt"))
    writeLines(result$stdout, stdout_file, useBytes = TRUE)
    writeLines(result$stderr, stderr_file, useBytes = TRUE)

    graceful <- grepl("case_status: GRACEFUL_FAILURE", result$stdout, fixed = TRUE)
    passed <- identical(result$status, 0L) &&
      grepl("case_status: PASS", result$stdout, fixed = TRUE)
    classification <- if (isTRUE(result$timeout)) {
      "TIMEOUT"
    } else if (passed) {
      "PASS"
    } else if (graceful) {
      "GRACEFUL_FAILURE"
    } else {
      "CRASH_OR_NONZERO"
    }
    expected_depth_guard <- identical(classification, "GRACEFUL_FAILURE") &&
      grepl("safe recursion depth", result$stdout, fixed = TRUE)
    mandatory_size_failure <- taxa <= 500L &&
      !identical(classification, "PASS")
    unexpected_graceful <- identical(classification, "GRACEFUL_FAILURE") &&
      !expected_depth_guard
    if (identical(classification, "CRASH_OR_NONZERO") ||
        mandatory_size_failure || unexpected_graceful) {
      hard_failure <- TRUE
    }
    bytes_hit <- regmatches(
      result$stdout,
      regexpr("newick_bytes: [0-9]+", result$stdout)
    )
    newick_bytes <- if (length(bytes_hit) && nzchar(bytes_hit)) {
      as.integer(sub("newick_bytes: ", "", bytes_hit, fixed = TRUE))
    } else {
      NA_integer_
    }
    rows[[length(rows) + 1L]] <- data.frame(
      operation = operation,
      taxa = taxa,
      depth = taxa - 1L,
      newick_bytes = newick_bytes,
      classification = classification,
      exit_status = result$status,
      timed_out = isTRUE(result$timeout),
      stdout_file = basename(stdout_file),
      stderr_file = basename(stderr_file),
      stringsAsFactors = FALSE
    )
    if (!identical(classification, "PASS")) {
      break
    }
  }
}

results <- do.call(rbind, rows)
utils::write.table(
  results,
  file = file.path(output_dir, "RESULTS.tsv"),
  sep = "\t", quote = FALSE, row.names = FALSE, na = ""
)

summary_lines <- character()
for (operation in operations) {
  one <- results[results$operation == operation, , drop = FALSE]
  passed <- one[one$classification == "PASS", , drop = FALSE]
  graceful <- one[one$classification == "GRACEFUL_FAILURE", , drop = FALSE]
  crash_timeout <- one[one$classification %in% c("CRASH_OR_NONZERO", "TIMEOUT"), , drop = FALSE]
  summary_lines <- c(
    summary_lines,
    sprintf("operation: %s", operation),
    sprintf(
      "maximum_passing_taxa: %s",
      if (nrow(passed)) max(passed$taxa) else "NONE"
    ),
    sprintf(
      "first_graceful_failure_taxa: %s",
      if (nrow(graceful)) graceful$taxa[[1L]] else "NONE"
    ),
    sprintf(
      "first_crash_or_timeout_taxa: %s",
      if (nrow(crash_timeout)) crash_timeout$taxa[[1L]] else "NONE"
    ),
    sprintf(
      "first_crash_or_timeout_class: %s",
      if (nrow(crash_timeout)) crash_timeout$classification[[1L]] else "NONE"
    )
  )
}
summary_lines <- c(
  summary_lines,
  sprintf("direct_crash_or_unclassified_nonzero_observed: %s", hard_failure),
  sprintf("overall_probe_status: %s", if (hard_failure) "FAIL" else "PASS"),
  sprintf("finished_utc: %s", format(Sys.time(), tz = "UTC", usetz = TRUE))
)
writeLines(summary_lines, file.path(output_dir, "SUMMARY.txt"), useBytes = TRUE)
if (hard_failure) {
  stop("deep-tree probe observed a crash or unclassified nonzero exit")
}
cat("deep_tree_probe: PASS\n")
