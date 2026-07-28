args <- commandArgs(trailingOnly = TRUE)
case_ids <- c(
  "dll_locale",
  "dll_noop",
  "dll_strtod",
  "dll_ascii_marker",
  "dll_regex_automatic",
  "dll_regex_static",
  "dll_frozen_numeric",
  "package_core_info",
  "package_numeric_validator"
)
if (length(args) != 2L || !args[[1L]] %in% case_ids) {
  stop(
    paste0(
      "usage: windows_r_hosted_case.R CASE_ID DLL_PATH; CASE_ID in ",
      paste(case_ids, collapse = ",")
    ),
    call. = FALSE
  )
}
case_id <- args[[1L]]
dll_path <- normalizePath(args[[2L]], winslash = "/", mustWork = TRUE)

emit <- function(key, value = NULL) {
  if (is.null(value)) {
    cat(key, "\n", sep = "")
  } else {
    cat(key, ": ", value, "\n", sep = "")
  }
  flush.console()
}

time_call <- function(label, callback) {
  upper <- toupper(label)
  emit(paste0("stage_marker: ", upper, "_STARTED"))
  started <- proc.time()[["elapsed"]]
  value <- callback()
  elapsed <- proc.time()[["elapsed"]] - started
  emit(paste0("stage_marker: ", upper, "_FINISHED"))
  emit(paste0("timing_", label, "_wall_seconds"), sprintf("%.9f", elapsed))
  value
}

emit("stage_marker: SCRIPT_STARTED")
emit("case_id", case_id)
emit("fresh_process_pid", Sys.getpid())
emit("started_utc", format(Sys.time(), tz = "UTC", usetz = TRUE))
emit("R_version", R.version.string)
emit("R_platform", R.version$platform)
emit("locale_evidence_case", "dll_locale")

dll_cases <- startsWith(case_id, "dll_")
if (dll_cases) {
  emit("diagnostic_dll_path", dll_path)
  emit("stage_marker: DLL_LOAD_STARTED")
  dll <- dyn.load(dll_path, local = TRUE, now = TRUE)
  on.exit(dyn.unload(dll_path), add = TRUE)
  emit("loaded_dll_name", dll[["name"]])
  emit("loaded_dll_path", normalizePath(dll[["path"]], winslash = "/"))
  emit("loaded_dll_dynamic_lookup", dll[["dynamicLookup"]])
  emit("stage_marker: DLL_LOAD_FINISHED")
} else {
  suppressPackageStartupMessages(library(SplitAlignerR))
  emit("stage_marker: PACKAGE_LOADED")
}

callbacks <- list(
  dll_locale = function() .Call("sar_fix007_locale"),
  dll_noop = function() .Call("sar_fix007_noop"),
  dll_strtod = function() .Call("sar_fix007_strtod"),
  dll_ascii_marker = function() .Call("sar_fix007_ascii_marker"),
  dll_regex_automatic = function() .Call("sar_fix007_regex_automatic"),
  dll_regex_static = function() .Call("sar_fix007_regex_static"),
  dll_frozen_numeric = function() .Call("sar_fix007_frozen_numeric"),
  package_core_info = function() {
    getFromNamespace("cpp_splitaligner_core_info", "SplitAlignerR")()
  },
  package_numeric_validator = function() {
    SplitAlignerR::validate_branch_length_tokens("1")
  }
)

validate_value <- function(value) {
  if (identical(case_id, "dll_locale")) {
    stopifnot(
      is.character(value),
      identical(names(value), c("LC_CTYPE", "LC_COLLATE", "LC_NUMERIC")),
      length(value) == 3L,
      all(nzchar(value))
    )
  } else if (dll_cases) {
    stopifnot(identical(value, TRUE))
  } else if (identical(case_id, "package_core_info")) {
    stopifnot(
      is.list(value),
      identical(value$production_language, "C++17"),
      identical(value$numeric_policy, "finite-double-v1")
    )
  } else {
    stopifnot(
      identical(value$accepted, TRUE),
      identical(value$classification, "finite_numeric"),
      identical(value$value, 1)
    )
  }
}

if (!identical(case_id, "dll_locale")) {
  emit("locale_values", "see fresh dll_locale case")
  emit("stage_marker: LOCALE_RECORDED")
}

emit("stage_marker: OPERATION_STARTED")
result <- tryCatch(
  {
    first <- time_call(paste0(case_id, "_first_call"), callbacks[[case_id]])
    validate_value(first)
    second <- time_call(paste0(case_id, "_second_call"), callbacks[[case_id]])
    validate_value(second)
    if (identical(case_id, "dll_locale")) {
      stopifnot(identical(first, second))
      emit("LC_CTYPE", first[["LC_CTYPE"]])
      emit("LC_COLLATE", first[["LC_COLLATE"]])
      emit("LC_NUMERIC", first[["LC_NUMERIC"]])
      emit("stage_marker: LOCALE_RECORDED")
    }
    TRUE
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
emit("finished_utc", format(Sys.time(), tz = "UTC", usetz = TRUE))
quit(save = "no", status = 0L, runLast = FALSE)
