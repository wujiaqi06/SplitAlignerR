#' Catnip10 benchmark status counts
#'
#' Summarize the bundled Catnip10 graph-oracle benchmark by deletion regime and
#' primitive-cell status. The benchmark is discordance-free, so `NA_topo` is
#' expected to be zero in this benchmark fixture.
#'
#' @param regime Character; `"all"` returns both bundled regimes, otherwise one
#'   of `"global"` or `"local"`.
#' @return A base `data.frame` with columns `regime`, `observed`, `NA_fuse`,
#'   `NA_struct`, `NA_topo`, and `total`.
#' @examples
#' catnip10_summary_counts()
#' @export
catnip10_summary_counts <- function(regime = c("all", "global", "local")) {
  regime <- match.arg(regime)
  regimes <- if (identical(regime, "all")) c("global", "local") else regime

  rows <- lapply(regimes, function(one_regime) {
    status <- catnip10_status_values(one_regime)
    counts <- table(status, useNA = "no")

    data.frame(
      regime = one_regime,
      observed = catnip10_count_value(counts, "observed"),
      NA_fuse = catnip10_count_value(counts, "NA_fuse"),
      NA_struct = catnip10_count_value(counts, "NA_struct"),
      NA_topo = catnip10_count_value(counts, "NA_topo"),
      total = length(status),
      check.names = FALSE,
      stringsAsFactors = FALSE
    )
  })

  out <- do.call(rbind, rows)
  rownames(out) <- NULL
  out
}

#' Validate the bundled Catnip10 oracle data
#'
#' Run deterministic checks for the bundled Catnip10 graph-oracle data. In
#' addition to data loading and accounting checks, the pure R node-edge oracle is
#' rerun for both deletion regimes and compared exactly with the frozen matrix,
#' per-cell ledger, and fusion groups. The Oracle remains independent of the
#' production C++ mapper; this helper validates the Oracle track, not final
#' release certification.
#'
#' @return A base `data.frame` with columns `check`, `status`, and `details`.
#'   `status` is one of `PASS`, `FAIL`, or `DEFERRED`.
#' @examples
#' validate_catnip10_oracle()
#' @export
validate_catnip10_oracle <- function() {
  rows <- list()
  add <- function(check, status, details) {
    rows[[length(rows) + 1L]] <<- data.frame(
      check = check,
      status = status,
      details = details,
      stringsAsFactors = FALSE
    )
  }

  data_loaded <- exists("catnip10_oracle", inherits = TRUE) &&
    is.list(catnip10_oracle) &&
    all(c("global", "local") %in% names(catnip10_oracle))
  add(
    "package_data_loads",
    if (data_loaded) "PASS" else "FAIL",
    if (data_loaded) "catnip10_oracle contains global and local regimes" else
      "catnip10_oracle is missing or incomplete"
  )

  topo_count <- 0L
  if (data_loaded) {
    all_status <- unlist(
      lapply(c("global", "local"), catnip10_status_values),
      use.names = FALSE
    )
    topo_count <- sum(all_status == "NA_topo", na.rm = TRUE)
  }
  add(
    "no_unexpected_NA_topo_in_discordance_free_benchmark",
    if (data_loaded && topo_count == 0L) "PASS" else "FAIL",
    sprintf("NA_topo cells observed: %d", topo_count)
  )

  counts <- tryCatch(catnip10_summary_counts(), error = function(e) e)
  required_cols <- c("regime", "observed", "NA_fuse", "NA_struct", "NA_topo", "total")
  counts_ok <- is.data.frame(counts) &&
    all(required_cols %in% names(counts)) &&
    nrow(counts) > 0L &&
    all(counts$total > 0L)
  add(
    "status_counts_available",
    if (counts_ok) "PASS" else if (data_loaded) "FAIL" else "DEFERRED",
    if (counts_ok) {
      paste(
        sprintf(
          "%s total=%s observed=%s NA_fuse=%s NA_struct=%s NA_topo=%s",
          counts$regime,
          counts$total,
          counts$observed,
          counts$NA_fuse,
          counts$NA_struct,
          counts$NA_topo
        ),
        collapse = "; "
      )
    } else if (inherits(counts, "error")) {
      conditionMessage(counts)
    } else {
      "Summary counts did not return a nonempty data frame with the required columns"
    }
  )

  dims_ok <- data_loaded && all(vapply(c("global", "local"), function(one_regime) {
    m <- catnip10_oracle[[one_regime]]$matrix
    is.data.frame(m) && identical(dim(m), c(8L, 18L))
  }, logical(1)))
  add(
    "matrix_dimensions_match_seed_oracle",
    if (dims_ok) "PASS" else "FAIL",
    "Expected each regime matrix to be 8 rows x 18 columns"
  )

  for (regime in c("global", "local")) {
    rebuilt <- tryCatch(
      recompute_catnip10_oracle(regime),
      error = function(e) e
    )
    frozen <- if (data_loaded) catnip10_oracle[[regime]] else NULL
    exact <- is.list(rebuilt) && is.list(frozen) &&
      identical(rebuilt$matrix, frozen$matrix) &&
      identical(rebuilt$status_long, frozen$status_long) &&
      identical(rebuilt$fusion_groups, frozen$fusion_groups)
    details <- if (inherits(rebuilt, "error")) {
      conditionMessage(rebuilt)
    } else if (exact) {
      "136/136 primitive cells and all fusion groups match the frozen oracle"
    } else {
      "Recomputed matrix, cell ledger, or fusion groups differ from the frozen oracle"
    }
    add(
      paste0("pure_R_graph_oracle_exact_", regime),
      if (exact) "PASS" else "FAIL",
      details
    )
  }

  do.call(rbind, rows)
}

#' Catnip10 fused-coordinate groups
#'
#' Return the bundled graph-oracle fused-coordinate membership table for one or
#' both Catnip10 deletion regimes.
#'
#' @param regime Character; `"all"` returns both bundled regimes, otherwise one
#'   of `"global"` or `"local"`.
#' @return A base `data.frame`. When `regime = "all"`, a leading `regime`
#'   column is added.
#' @examples
#' head(catnip10_fusion_groups())
#' @export
catnip10_fusion_groups <- function(regime = c("all", "global", "local")) {
  regime <- match.arg(regime)
  regimes <- if (identical(regime, "all")) c("global", "local") else regime

  rows <- lapply(regimes, function(one_regime) {
    groups <- catnip10_oracle[[one_regime]]$fusion_groups
    if (!is.data.frame(groups)) {
      stop(
        "Required fusion-group data are unavailable; the installed package is incomplete.",
        call. = FALSE
      )
    }
    if (identical(regime, "all")) {
      groups <- data.frame(
        regime = one_regime,
        groups,
        check.names = FALSE,
        stringsAsFactors = FALSE
      )
    }
    groups
  })

  out <- do.call(rbind, rows)
  rownames(out) <- NULL
  out
}

#' Catnip10 wide primitive-coordinate matrix
#'
#' Return the bundled wide graph-oracle matrix for one Catnip10 deletion regime.
#'
#' @param regime Deletion regime: `"global"` or `"local"`.
#' @return A base `data.frame` with `gene_id` plus 17 primitive branch
#'   coordinates.
#' @examples
#' catnip10_matrix("global")
#' @export
catnip10_matrix <- function(regime = c("global", "local")) {
  regime <- match.arg(regime)
  matrix <- catnip10_oracle[[regime]]$matrix
  if (!is.data.frame(matrix)) {
    stop(
      "Required Catnip10 matrix data are unavailable; the installed package is incomplete.",
      call. = FALSE
    )
  }
  matrix
}

catnip10_status_values <- function(regime) {
  status_long <- catnip10_oracle[[regime]]$status_long
  if (is.data.frame(status_long) && "status" %in% names(status_long)) {
    status <- as.character(status_long$status)
    status[status == "observed"] <- "observed"
    return(status)
  }

  matrix <- catnip10_oracle[[regime]]$matrix
  if (!is.data.frame(matrix)) {
    return(character())
  }
  values <- unlist(matrix[setdiff(names(matrix), "gene_id")], use.names = FALSE)
  ifelse(
    values %in% c("NA_fuse", "NA_struct", "NA_topo"),
    values,
    "observed"
  )
}

catnip10_count_value <- function(counts, label) {
  if (label %in% names(counts)) {
    return(as.integer(unname(counts[[label]])))
  }
  0L
}
