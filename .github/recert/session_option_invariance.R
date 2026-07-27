args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1L) {
  stop("usage: session_option_invariance.R OUTPUT_TSV", call. = FALSE)
}

output_tsv <- args[[1L]]
suppressPackageStartupMessages(library(SplitAlignerR))

with_session_options <- function(values, code) {
  old <- options(values)
  on.exit(options(old), add = TRUE)
  force(code)
}

sanitize_error <- function(value) {
  gsub("[\t\r\n]+", " ", value)
}

settings <- data.frame(
  outdec = c(".", ".", ".", ",", ",", ","),
  scipen = c(0L, -999L, 999L, 0L, -999L, 999L),
  stringsAsFactors = FALSE
)
numeric_values <- c(0, -0, 1.5, -2.25, 1.2e-8, 1e100)
frozen_oracle <- get(
  "catnip10_oracle",
  envir = as.environment("package:SplitAlignerR")
)
finalize_cells <- getFromNamespace("finalize_paired_cells", "SplitAlignerR")
validate_matrix <- getFromNamespace(
  "validate_finalized_token_matrix", "SplitAlignerR"
)

canonical_numeric_contract <- function(tokens) {
  if (length(tokens) != length(numeric_values) ||
      !identical(tokens[seq_len(4L)], c("0", "-0", "1.5", "-2.25")) ||
      !grepl("^1\\.2[eE]-0*8$", tokens[[5L]]) ||
      !grepl(
        "^[0-9]+(?:\\.[0-9]+)?[eE]\\+?0*100$",
        tokens[[6L]], perl = TRUE
      ) ||
      any(grepl(",", tokens, fixed = TRUE))) {
    return(FALSE)
  }
  checked <- SplitAlignerR::validate_branch_length_tokens(tokens)
  all(checked$accepted) && isTRUE(all.equal(
    checked$value, numeric_values, tolerance = 0
  ))
}

sentinel_restoration_check <- function() {
  before <- options(c("OutDec", "scipen"))
  on.exit(options(before), add = TRUE)
  probe_outdec <- if (identical(before$OutDec, ".")) "," else "."
  probe_scipen <- if (identical(as.numeric(before$scipen), 987)) {
    -987L
  } else {
    987L
  }
  caught <- tryCatch(
    with_session_options(
      list(OutDec = probe_outdec, scipen = probe_scipen),
      stop("sentinel session-option failure", call. = FALSE)
    ),
    error = function(error) {
      identical(
        conditionMessage(error),
        "sentinel session-option failure"
      )
    }
  )
  isTRUE(caught) && identical(options(c("OutDec", "scipen")), before)
}

public_snapshot <- function() {
  species <- ape::read.tree(text = "((A,B),(C,D));")
  gene <- ape::read.tree(text = "((A:1.5,B:2):3,(C:4,D:5):6);")
  multi <- structure(list(g1 = gene, g2 = gene), class = "multiPhylo")
  gene_list <- unclass(multi)
  fixed <- SplitAlignerR::align_branches(
    species, gene, mode = "fixed", gene_ids = "g"
  )
  free <- SplitAlignerR::align_branches(
    species, gene, mode = "free", gene_ids = "g"
  )
  list(
    fixed = fixed,
    free = free,
    paired = SplitAlignerR::pair_alignment_results(fixed, free),
    multi = SplitAlignerR::align_branches(species, multi, mode = "free"),
    phylo_list = SplitAlignerR::align_branches(
      species, gene_list, mode = "free"
    )
  )
}

case_payload <- function(outdec, scipen) {
  with_session_options(
    list(OutDec = outdec, scipen = scipen),
    {
      finalized <- finalize_cells(
        fixed_state = rep("mapped", length(numeric_values)),
        fixed_primitive_numeric = numeric_values,
        fixed_fused_numeric = rep(NA_real_, length(numeric_values)),
        free_state = rep("mapped", length(numeric_values)),
        free_primitive_numeric = numeric_values,
        free_fused_numeric = rep(NA_real_, length(numeric_values))
      )
      validate_matrix(matrix(finalized$fixed_output_token, nrow = 1L))
      validate_matrix(matrix(
        finalized$free_pre_promotion_token, nrow = 1L
      ))
      validate_matrix(matrix(finalized$final_matrix_token, nrow = 1L))
      public <- public_snapshot()
      global <- SplitAlignerR::recompute_catnip10_oracle("global")
      local <- SplitAlignerR::recompute_catnip10_oracle("local")
      list(
        finalized = finalized,
        public = public,
        oracle_global = global,
        oracle_local = local
      )
    }
  )
}

reference <- case_payload(".", 0L)
rows <- vector("list", nrow(settings))

for (i in seq_len(nrow(settings))) {
  outdec <- settings$outdec[[i]]
  scipen <- settings$scipen[[i]]
  before <- options(c("OutDec", "scipen"))
  error_text <- ""
  payload <- tryCatch(
    case_payload(outdec, scipen),
    error = function(error) {
      error_text <<- sanitize_error(conditionMessage(error))
      NULL
    }
  )
  options_restored <- identical(options(c("OutDec", "scipen")), before)
  error_options_restored <- sentinel_restoration_check()

  if (is.null(payload)) {
    checks <- c(rep(FALSE, 6L), options_restored, error_options_restored)
  } else {
    finalized <- payload$finalized
    public_tokens <- as.vector(payload$public$paired$final_matrix)
    state <- public_tokens %in% c("NA", "NA_struct", "NA_fuse", "NA_topo")
    canonical_tokens_invariant <-
      identical(
        finalized$fixed_output_token,
        reference$finalized$fixed_output_token
      ) &&
      identical(
        finalized$free_pre_promotion_token,
        reference$finalized$free_pre_promotion_token
      ) &&
      identical(
        finalized$final_matrix_token,
        reference$finalized$final_matrix_token
      ) &&
      identical(
        finalized$summary_class,
        rep("numeric", length(numeric_values))
      ) &&
      "1.5" %in% public_tokens[!state] &&
      !any(grepl(",", public_tokens[!state], fixed = TRUE))
    canonical_value_contract <-
      canonical_numeric_contract(finalized$fixed_output_token) &&
      canonical_numeric_contract(finalized$free_pre_promotion_token) &&
      canonical_numeric_contract(finalized$final_matrix_token)
    validator_accepts <-
      all(SplitAlignerR::validate_branch_length_tokens(
        public_tokens[!state]
      )$accepted)
    checks <- c(
      identical(payload$public, reference$public),
      canonical_tokens_invariant,
      canonical_value_contract,
      validator_accepts,
      identical(payload$oracle_global, frozen_oracle$global),
      identical(payload$oracle_local, frozen_oracle$local),
      options_restored,
      error_options_restored
    )
  }

  rows[[i]] <- data.frame(
    outdec = outdec,
    scipen = scipen,
    lc_numeric = Sys.getlocale("LC_NUMERIC"),
    public_objects_identical = checks[[1L]],
    canonical_tokens_invariant = checks[[2L]],
    canonical_value_contract = checks[[3L]],
    validator_accepts = checks[[4L]],
    oracle_global_identical = checks[[5L]],
    oracle_local_identical = checks[[6L]],
    options_restored = checks[[7L]],
    error_options_restored = checks[[8L]],
    overall_status = if (all(checks)) "PASS" else "FAIL",
    error = error_text,
    stringsAsFactors = FALSE,
    check.names = FALSE
  )
}

result <- do.call(rbind, rows)
utils::write.table(
  result,
  file = output_tsv,
  sep = "\t",
  quote = FALSE,
  row.names = FALSE,
  col.names = TRUE,
  na = "",
  eol = "\n",
  fileEncoding = "UTF-8",
  dec = "."
)

if (!all(result$overall_status == "PASS")) {
  failed <- paste(
    paste0(
      "OutDec=", result$outdec[result$overall_status != "PASS"],
      ";scipen=", result$scipen[result$overall_status != "PASS"]
    ),
    collapse = ", "
  )
  stop("SESSION_OPTION_INVARIANCE failed: ", failed, call. = FALSE)
}

cat(sprintf(
  "SESSION_OPTION_INVARIANCE: PASS (%d/%d combinations)\n",
  sum(result$overall_status == "PASS"), nrow(result)
))
