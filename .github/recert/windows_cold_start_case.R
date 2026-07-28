args <- commandArgs(trailingOnly = TRUE)
case_ids <- c(
  "numeric_validator",
  "align_fixed_no_prewarm",
  "align_fixed_prewarm",
  "align_no_length_fixed",
  "align_free_no_prewarm",
  "wrapper_core_boundary"
)
if (length(args) != 1L || !args[[1L]] %in% case_ids) {
  stop(
    paste0("usage: windows_cold_start_case.R CASE_ID; CASE_ID in ",
           paste(case_ids, collapse = ",")),
    call. = FALSE
  )
}
case_id <- args[[1L]]

emit <- function(key, value = NULL) {
  if (is.null(value)) {
    cat(key, "\n", sep = "")
  } else {
    cat(key, ": ", value, "\n", sep = "")
  }
  flush.console()
}

time_call <- function(label, callback) {
  emit(paste0("stage_marker: ", toupper(label), "_STARTED"))
  started <- proc.time()[["elapsed"]]
  value <- callback()
  elapsed <- proc.time()[["elapsed"]] - started
  emit(paste0("stage_marker: ", toupper(label), "_FINISHED"))
  emit(paste0("timing_", label, "_wall_seconds"), sprintf("%.9f", elapsed))
  list(value = value, elapsed = elapsed)
}

comb_newick <- function(taxa = 10L, lengths = TRUE) {
  labels <- sprintf("t%06d", seq_len(taxa))
  if (lengths) {
    tree <- sprintf("(%s:1,%s:1):1", labels[[1L]], labels[[2L]])
    if (taxa > 2L) {
      for (i in 3:taxa) {
        tree <- sprintf("(%s,%s:1):1", tree, labels[[i]])
      }
    }
  } else {
    tree <- sprintf("(%s,%s)", labels[[1L]], labels[[2L]])
    if (taxa > 2L) {
      for (i in 3:taxa) {
        tree <- sprintf("(%s,%s)", tree, labels[[i]])
      }
    }
  }
  paste0(tree, ";")
}

emit("stage_marker: SCRIPT_STARTED")
emit("case_id", case_id)
emit("fresh_process_pid", Sys.getpid())
emit("started_utc", format(Sys.time(), tz = "UTC", usetz = TRUE))
suppressPackageStartupMessages(library(SplitAlignerR))
emit("stage_marker: PACKAGE_LOADED")

with_lengths <- comb_newick(10L, lengths = TRUE)
without_lengths <- comb_newick(10L, lengths = FALSE)
emit("generator_id", "deterministic_left_comb_v1")
emit("taxa", 10L)
emit("with_lengths_newick_bytes", nchar(with_lengths, type = "bytes"))
emit("without_lengths_newick_bytes", nchar(without_lengths, type = "bytes"))
emit("stage_marker: INPUT_READY")
emit("stage_marker: OPERATION_STARTED")

result <- tryCatch(
  {
    if (identical(case_id, "numeric_validator")) {
      first <- time_call("numeric_first_call", function() {
        SplitAlignerR::validate_branch_length_tokens("1")
      })
      second <- time_call("numeric_second_call", function() {
        SplitAlignerR::validate_branch_length_tokens("1")
      })
      stopifnot(
        identical(first$value$accepted, TRUE),
        identical(second$value$accepted, TRUE),
        identical(first$value$classification, "finite_numeric"),
        identical(second$value$classification, "finite_numeric")
      )
      list(result_class = "numeric_validator", cells = 1L)
    } else if (identical(case_id, "align_fixed_no_prewarm")) {
      aligned <- time_call("align_fixed", function() {
        SplitAlignerR::align_branches(
          with_lengths, with_lengths, mode = "fixed",
          gene_ids = "cold_comb_gene"
        )
      })$value
      list(
        result_class = "fixed_alignment",
        tips = aligned$species_tree$metadata$tip_count,
        coordinates = ncol(aligned$state_matrix)
      )
    } else if (identical(case_id, "align_fixed_prewarm")) {
      warmed <- time_call("numeric_prewarm", function() {
        SplitAlignerR::validate_branch_length_tokens("1")
      })$value
      stopifnot(identical(warmed$accepted, TRUE))
      aligned <- time_call("align_fixed_after_prewarm", function() {
        SplitAlignerR::align_branches(
          with_lengths, with_lengths, mode = "fixed",
          gene_ids = "cold_comb_gene"
        )
      })$value
      list(
        result_class = "fixed_alignment_after_numeric_prewarm",
        tips = aligned$species_tree$metadata$tip_count,
        coordinates = ncol(aligned$state_matrix)
      )
    } else if (identical(case_id, "align_no_length_fixed")) {
      aligned <- time_call("align_no_length_fixed", function() {
        SplitAlignerR::align_branches(
          without_lengths, without_lengths, mode = "fixed",
          gene_ids = "cold_comb_gene"
        )
      })$value
      list(
        result_class = "fixed_alignment_no_lengths",
        tips = aligned$species_tree$metadata$tip_count,
        coordinates = ncol(aligned$state_matrix)
      )
    } else if (identical(case_id, "align_free_no_prewarm")) {
      aligned <- time_call("align_free", function() {
        SplitAlignerR::align_branches(
          with_lengths, with_lengths, mode = "free",
          gene_ids = "cold_comb_gene"
        )
      })$value
      list(
        result_class = "free_alignment",
        tips = aligned$species_tree$metadata$tip_count,
        coordinates = ncol(aligned$state_matrix)
      )
    } else {
      as_species_newick <- getFromNamespace(
        "as_species_newick", "SplitAlignerR"
      )
      as_gene_newicks <- getFromNamespace(
        "as_gene_newicks", "SplitAlignerR"
      )
      cpp_align_branches <- getFromNamespace(
        "cpp_align_branches", "SplitAlignerR"
      )
      species <- time_call("as_species_newick", function() {
        as_species_newick(with_lengths)
      })$value
      genes <- time_call("as_gene_newicks", function() {
        as_gene_newicks(with_lengths, gene_ids = "cold_comb_gene")
      })$value
      raw <- time_call("cpp_align_branches", function() {
        cpp_align_branches(
          species$text, genes$newicks, genes$ids, "fixed"
        )
      })$value
      list(
        result_class = "wrapper_core_boundary",
        tips = raw$species_tree$metadata$tip_count,
        coordinates = ncol(raw$state_matrix)
      )
    }
  },
  error = function(error) error
)

emit("stage_marker: OPERATION_FINISHED")
if (inherits(result, "error")) {
  emit("case_status", "GRACEFUL_FAILURE")
  emit("error_class", paste(class(result), collapse = ","))
  emit("error_message", gsub("[\t\r\n]+", " ", conditionMessage(result)))
  quit(save = "no", status = 2L, runLast = FALSE)
}

emit("case_status", "PASS")
emit("result_class", result$result_class)
if (!is.null(result$tips)) {
  emit("result_tips", result$tips)
}
if (!is.null(result$coordinates)) {
  emit("result_coordinates", result$coordinates)
}
emit("finished_utc", format(Sys.time(), tz = "UTC", usetz = TRUE))
quit(save = "no", status = 0L, runLast = FALSE)
