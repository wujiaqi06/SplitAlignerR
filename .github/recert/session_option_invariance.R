args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1L) {
  stop("usage: session_option_invariance.R OUTPUT_TSV", call. = FALSE)
}

output_tsv <- args[[1L]]
suppressPackageStartupMessages(library(SplitAlignerR))

sanitize_text <- function(value) {
  gsub("[\t\r\n]+", " ", value)
}

with_session_options <- function(values, code) {
  old <- options(values)
  on.exit(options(old), add = TRUE)
  force(code)
}

mandatory_settings <- data.frame(
  case_kind = "mandatory",
  requested_outdec = rep(c(".", ","), each = 3L),
  requested_scipen = rep(c(-9L, 0L, 999L), times = 2L),
  stringsAsFactors = FALSE
)
optional_settings <- data.frame(
  case_kind = "optional_extreme",
  requested_outdec = c(".", ","),
  requested_scipen = rep(-999L, 2L),
  stringsAsFactors = FALSE
)
settings <- rbind(mandatory_settings, optional_settings)

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
  before <- options("OutDec", "scipen")
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
  isTRUE(caught) && identical(options("OutDec", "scipen"), before)
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

case_payload <- function() {
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
  list(
    finalized = finalized,
    public = public_snapshot(),
    oracle_global = SplitAlignerR::recompute_catnip10_oracle("global"),
    oracle_local = SplitAlignerR::recompute_catnip10_oracle("local")
  )
}

evaluate_case <- function(requested_outdec, requested_scipen) {
  before <- options("OutDec", "scipen")
  on.exit(options(before), add = TRUE)
  option_warnings <- character()
  error_text <- ""
  effective_outdec <- NA_character_
  effective_scipen <- NA_real_

  applied <- tryCatch(
    {
      withCallingHandlers(
        options(
          OutDec = requested_outdec,
          scipen = requested_scipen
        ),
        warning = function(warning) {
          option_warnings <<- c(
            option_warnings,
            sanitize_text(conditionMessage(warning))
          )
        }
      )
      effective_outdec <- getOption("OutDec")
      effective_scipen <- getOption("scipen")
      TRUE
    },
    error = function(error) {
      error_text <<- sanitize_text(conditionMessage(error))
      FALSE
    }
  )

  payload <- NULL
  if (applied) {
    payload <- tryCatch(
      case_payload(),
      error = function(error) {
        error_text <<- sanitize_text(conditionMessage(error))
        NULL
      }
    )
  }

  list(
    payload = payload,
    effective_outdec = effective_outdec,
    effective_scipen = effective_scipen,
    option_warning = paste(unique(option_warnings), collapse = " | "),
    error = error_text
  )
}

reference_case <- evaluate_case(".", 0L)
if (is.null(reference_case$payload) ||
    !identical(reference_case$effective_outdec, ".") ||
    !identical(as.numeric(reference_case$effective_scipen), 0)) {
  stop("Unable to construct the exact default-session reference.", call. = FALSE)
}
reference <- reference_case$payload
rows <- vector("list", nrow(settings))

for (i in seq_len(nrow(settings))) {
  case_kind <- settings$case_kind[[i]]
  requested_outdec <- settings$requested_outdec[[i]]
  requested_scipen <- settings$requested_scipen[[i]]
  before <- options("OutDec", "scipen")
  evaluated <- evaluate_case(requested_outdec, requested_scipen)
  options_restored <- identical(options("OutDec", "scipen"), before)
  error_options_restored <- sentinel_restoration_check()
  payload <- evaluated$payload
  effective_outdec <- evaluated$effective_outdec
  effective_scipen <- evaluated$effective_scipen
  option_exactly_applied <-
    identical(effective_outdec, requested_outdec) &&
    !is.na(effective_scipen) &&
    identical(as.numeric(effective_scipen), as.numeric(requested_scipen))

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

  semantic_checks_pass <- all(checks)
  if (identical(case_kind, "mandatory")) {
    case_status <- if (semantic_checks_pass && option_exactly_applied) {
      "MANDATORY_PASS"
    } else {
      "MANDATORY_FAIL"
    }
  } else if (!semantic_checks_pass) {
    case_status <- "OPTIONAL_EXTREME_FAIL"
  } else if (option_exactly_applied) {
    case_status <- "OPTIONAL_EXTREME_PASS"
  } else {
    effective_label <- if (is.na(effective_scipen)) {
      "UNKNOWN"
    } else {
      format(effective_scipen, scientific = FALSE, trim = TRUE)
    }
    case_status <- paste0("NOT_AVAILABLE_CLAMPED_TO_", effective_label)
  }

  rows[[i]] <- data.frame(
    case_kind = case_kind,
    requested_outdec = requested_outdec,
    effective_outdec = effective_outdec,
    requested_scipen = requested_scipen,
    effective_scipen = effective_scipen,
    option_warning = evaluated$option_warning,
    option_exactly_applied = option_exactly_applied,
    case_status = case_status,
    lc_numeric = Sys.getlocale("LC_NUMERIC"),
    public_objects_identical = checks[[1L]],
    canonical_tokens_invariant = checks[[2L]],
    canonical_value_contract = checks[[3L]],
    validator_accepts = checks[[4L]],
    oracle_global_identical = checks[[5L]],
    oracle_local_identical = checks[[6L]],
    options_restored = checks[[7L]],
    error_options_restored = checks[[8L]],
    overall_status = if (
      case_status %in% c("MANDATORY_PASS", "OPTIONAL_EXTREME_PASS") ||
        startsWith(case_status, "NOT_AVAILABLE_CLAMPED_TO_")
    ) "PASS" else "FAIL",
    error = evaluated$error,
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
      "OutDec=", result$requested_outdec[result$overall_status != "PASS"],
      ";scipen=", result$requested_scipen[result$overall_status != "PASS"],
      ";status=", result$case_status[result$overall_status != "PASS"]
    ),
    collapse = ", "
  )
  stop("SESSION_OPTION_INVARIANCE failed: ", failed, call. = FALSE)
}

mandatory <- result[result$case_kind == "mandatory", , drop = FALSE]
optional <- result[result$case_kind == "optional_extreme", , drop = FALSE]
if (nrow(mandatory) != 6L ||
    !all(mandatory$case_status == "MANDATORY_PASS")) {
  stop("Portable mandatory option matrix did not pass 6/6.", call. = FALSE)
}

cat(sprintf(
  "SESSION_OPTION_INVARIANCE: PASS (%d/%d mandatory combinations)\n",
  sum(mandatory$case_status == "MANDATORY_PASS"), nrow(mandatory)
))
cat(sprintf(
  "SESSION_OPTION_EXTREME: %s (%d/%d cases)\n",
  paste(unique(optional$case_status), collapse = ","),
  sum(optional$overall_status == "PASS"), nrow(optional)
))
