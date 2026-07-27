args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2L) {
  stop("usage: deep_tree_case.R OPERATION TAXA", call. = FALSE)
}

operation <- match.arg(args[[1L]], c("validate_species_tree", "align_branches"))
taxa <- suppressWarnings(as.integer(args[[2L]]))
if (is.na(taxa) || taxa < 2L) {
  stop("TAXA must be an integer of at least 2", call. = FALSE)
}
cat("stage_marker: SCRIPT_STARTED\n")
flush.console()
suppressPackageStartupMessages(library(SplitAlignerR))
cat("stage_marker: PACKAGE_LOADED\n")
flush.console()

comb_newick <- function(taxa) {
  labels <- sprintf("t%06d", seq_len(taxa))
  tree <- sprintf("(%s:1,%s:1):1", labels[[1L]], labels[[2L]])
  if (taxa > 2L) {
    for (i in 3:taxa) {
      tree <- sprintf("(%s,%s:1):1", tree, labels[[i]])
    }
  }
  paste0(tree, ";")
}

compiler <- tryCatch(
  system2("R", c("CMD", "config", "CXX17"), stdout = TRUE, stderr = TRUE),
  error = function(e) conditionMessage(e)
)
tree <- comb_newick(taxa)
cat("stage_marker: INPUT_READY\n")
cat("generator_id: deterministic_left_comb_v1\n")
cat("generator_definition: start=(t000001:1,t000002:1):1; append=(previous,tNNNNNN:1):1; terminate=;\n")
cat(sprintf("operation: %s\n", operation))
cat(sprintf("taxa: %d\n", taxa))
cat(sprintf("comb_depth: %d\n", taxa - 1L))
cat(sprintf("newick_bytes: %d\n", nchar(tree, type = "bytes")))
cat(sprintf("os: %s %s\n", Sys.info()[["sysname"]], Sys.info()[["release"]]))
cat(sprintf("machine: %s\n", Sys.info()[["machine"]]))
cat(sprintf("R: %s\n", R.version.string))
cat(sprintf("R_platform: %s\n", R.version$platform))
cat(sprintf("compiler: %s\n", paste(compiler, collapse = " ")))
cat(sprintf("started_utc: %s\n", format(Sys.time(), tz = "UTC", usetz = TRUE)))
cat("stage_marker: OPERATION_STARTED\n")
flush.console()

started <- proc.time()
result <- tryCatch(
  {
    if (identical(operation, "validate_species_tree")) {
      validated <- validate_species_tree(tree)
      list(
        tips = validated$metadata$tip_count,
        coordinates = validated$metadata$coordinate_count
      )
    } else {
      aligned <- align_branches(
        tree, tree, mode = "fixed", gene_ids = "deep_comb_gene"
      )
      list(
        tips = aligned$species_tree$metadata$tip_count,
        coordinates = ncol(aligned$state_matrix),
        cells = length(aligned$state_matrix)
      )
    }
  },
  error = function(e) e
)
elapsed <- proc.time() - started
cat("stage_marker: OPERATION_FINISHED\n")
cat(sprintf("elapsed_wall_seconds: %.6f\n", unname(elapsed[["elapsed"]])))
cat(sprintf("elapsed_user_seconds: %.6f\n", unname(elapsed[["user.self"]])))
cat(sprintf("elapsed_system_seconds: %.6f\n", unname(elapsed[["sys.self"]])))
if (inherits(result, "error")) {
  cat("case_status: GRACEFUL_FAILURE\n")
  cat(sprintf("error_class: %s\n", paste(class(result), collapse = ",")))
  cat(sprintf("error_message: %s\n", conditionMessage(result)))
  quit(save = "no", status = 2L, runLast = FALSE)
}

cat("case_status: PASS\n")
cat("stage_marker: RESULT_SERIALIZATION_STARTED\n")
for (name in names(result)) {
  cat(sprintf("result_%s: %s\n", name, result[[name]]))
}
cat("stage_marker: CASE_FINISHED\n")
cat(sprintf("finished_utc: %s\n", format(Sys.time(), tz = "UTC", usetz = TRUE)))
