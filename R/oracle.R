# Independent Catnip10 graph oracle.
#
# This implementation intentionally uses only node-edge graph surgery. It must
# not call the production C++ core or use splits/projected splits to classify
# NA_struct or NA_fuse. The design is adapted from the frozen Benchmark V1
# oracle in the published SplitAligner RECERT-013 archive.

.oracle_root_sentinel <- "__ROOT__"

.oracle_freeze_tree_identity <- function(tree) {
  if (!inherits(tree, "phylo")) {
    stop("Oracle input must inherit from `phylo`.", call. = FALSE)
  }
  if (anyDuplicated(tree$tip.label)) {
    stop("Oracle input contains duplicated tip labels.", call. = FALSE)
  }
  if (is.null(tree$edge.length) || anyNA(tree$edge.length) ||
      any(!is.finite(tree$edge.length))) {
    stop("Oracle input requires finite branch lengths on every edge.", call. = FALSE)
  }

  n_tip <- length(tree$tip.label)
  tree$node.label <- paste0("N_", (n_tip + 1L):(n_tip + tree$Nnode))

  node_label <- function(node_id) {
    if (node_id <= n_tip) {
      tree$tip.label[node_id]
    } else {
      tree$node.label[node_id - n_tip]
    }
  }

  parent_labels <- vapply(tree$edge[, 1L], node_label, character(1))
  child_labels <- vapply(tree$edge[, 2L], node_label, character(1))
  root_labels <- setdiff(parent_labels, child_labels)
  if (length(root_labels) != 1L) {
    stop("Oracle could not determine one representation root.", call. = FALSE)
  }

  identity <- data.frame(
    parent_label = parent_labels,
    child_label = child_labels,
    branch_id = child_labels,
    branch_type = ifelse(tree$edge[, 2L] <= n_tip, "terminal", "internal"),
    branch_length = tree$edge.length,
    stringsAsFactors = FALSE
  )

  list(tree = tree, identity = identity, root_label = root_labels)
}

.oracle_init_state <- function(identity, root_label) {
  edges <- identity[, c(
    "parent_label", "child_label", "branch_length", "branch_type"
  )]
  edges$parent_label[edges$parent_label == root_label] <-
    .oracle_root_sentinel
  edges$member_ids <- lapply(identity$branch_id, function(id) id)
  edges$edge_uid <- seq_len(nrow(edges))
  rownames(edges) <- NULL

  list(
    edges = edges,
    next_edge_uid = nrow(edges) + 1L,
    tip_labels = as.character(
      identity$branch_id[identity$branch_type == "terminal"]
    )
  )
}

.oracle_incident_rows <- function(state, node_label) {
  which(
    state$edges$parent_label == node_label |
      state$edges$child_label == node_label
  )
}

.oracle_other_endpoint <- function(state, row_index, node_label) {
  if (state$edges$parent_label[row_index] == node_label) {
    return(as.character(state$edges$child_label[row_index]))
  }
  if (state$edges$child_label[row_index] == node_label) {
    return(as.character(state$edges$parent_label[row_index]))
  }
  stop("Oracle graph state contains a non-incident edge lookup.", call. = FALSE)
}

.oracle_choose_orientation <- function(state, endpoint_a, endpoint_b) {
  endpoints <- c(as.character(endpoint_a), as.character(endpoint_b))
  if (.oracle_root_sentinel %in% endpoints) {
    return(list(
      parent_label = .oracle_root_sentinel,
      child_label = setdiff(endpoints, .oracle_root_sentinel)[1L]
    ))
  }

  is_tip <- endpoints %in% state$tip_labels
  if (sum(is_tip) == 1L) {
    return(list(
      parent_label = endpoints[!is_tip][1L],
      child_label = endpoints[is_tip][1L]
    ))
  }

  endpoints <- sort(endpoints)
  list(parent_label = endpoints[1L], child_label = endpoints[2L])
}

.oracle_merge_rows <- function(state, row_a, row_b,
                               parent_label, child_label) {
  lengths <- c(
    state$edges$branch_length[row_a],
    state$edges$branch_length[row_b]
  )
  merged_length <- if (anyNA(lengths) || any(!is.finite(lengths))) {
    NA_real_
  } else {
    value <- sum(lengths)
    if (!is.finite(value)) {
      stop("Oracle edge-length sum is outside the finite numeric range.",
           call. = FALSE)
    }
    value
  }
  members <- sort(unique(c(
    state$edges$member_ids[[row_a]],
    state$edges$member_ids[[row_b]]
  )))
  branch_type <- if (
    state$edges$branch_type[row_a] == "internal" ||
      state$edges$branch_type[row_b] == "internal"
  ) {
    "internal"
  } else {
    "terminal"
  }

  state$edges <- state$edges[-sort(c(row_a, row_b)), , drop = FALSE]
  state$edges <- rbind(
    state$edges,
    data.frame(
      parent_label = parent_label,
      child_label = child_label,
      branch_length = merged_length,
      branch_type = branch_type,
      member_ids = I(list(members)),
      edge_uid = state$next_edge_uid,
      stringsAsFactors = FALSE
    )
  )
  state$next_edge_uid <- state$next_edge_uid + 1L
  rownames(state$edges) <- NULL
  state
}

.oracle_normalize_representation_root <- function(state) {
  repeat {
    root_rows <- which(
      state$edges$parent_label == .oracle_root_sentinel
    )
    if (length(root_rows) != 2L) {
      break
    }

    root_edges <- state$edges[root_rows, , drop = FALSE]
    root_rows <- root_rows[order(root_edges$child_label, root_edges$edge_uid)]
    endpoint_a <- state$edges$child_label[root_rows[1L]]
    endpoint_b <- state$edges$child_label[root_rows[2L]]

    state <- .oracle_merge_rows(
      state,
      root_rows[1L], root_rows[2L],
      parent_label = endpoint_a,
      child_label = endpoint_b
    )
  }
  state
}

.oracle_contract_degree2 <- function(state) {
  repeat {
    nodes <- sort(unique(c(
      state$edges$parent_label,
      state$edges$child_label
    )))
    nodes <- setdiff(
      nodes,
      c(.oracle_root_sentinel, state$tip_labels)
    )

    contracted <- FALSE
    for (node in nodes) {
      rows <- .oracle_incident_rows(state, node)
      if (length(rows) != 2L) {
        next
      }
      endpoint_a <- .oracle_other_endpoint(state, rows[1L], node)
      endpoint_b <- .oracle_other_endpoint(state, rows[2L], node)
      orientation <- .oracle_choose_orientation(
        state, endpoint_a, endpoint_b
      )
      state <- .oracle_merge_rows(
        state,
        rows[1L], rows[2L],
        orientation$parent_label,
        orientation$child_label
      )
      state <- .oracle_normalize_representation_root(state)
      contracted <- TRUE
      break
    }
    if (!contracted) {
      break
    }
  }
  state
}

.oracle_delete_tip <- function(state, tip_label) {
  tip_rows <- .oracle_incident_rows(state, tip_label)
  if (length(tip_rows) != 1L) {
    stop(
      sprintf("Expected exactly one current edge for tip `%s`.", tip_label),
      call. = FALSE
    )
  }
  state$edges <- state$edges[-tip_rows, , drop = FALSE]
  state <- .oracle_normalize_representation_root(state)
  .oracle_contract_degree2(state)
}

.oracle_format_length <- function(value) {
  if (is.na(value)) {
    return("")
  }
  format(value, digits = 10L, scientific = FALSE, trim = TRUE)
}

.oracle_classify_state <- function(state, identity) {
  axis <- as.character(identity$branch_id)
  values <- rep(NA_character_, length(axis))
  names(values) <- axis

  for (row_index in seq_len(nrow(state$edges))) {
    members <- sort(unique(as.character(
      state$edges$member_ids[[row_index]]
    )))
    if (length(members) == 1L) {
      values[members] <- .oracle_format_length(
        state$edges$branch_length[row_index]
      )
    } else {
      values[members] <- "NA_fuse"
    }
  }
  values[is.na(values)] <- "NA_struct"
  values
}

.oracle_fusion_rows <- function(state, gene_id, step_id) {
  rows <- list()
  group_index <- 0L
  for (row_index in seq_len(nrow(state$edges))) {
    members <- sort(unique(as.character(
      state$edges$member_ids[[row_index]]
    )))
    if (length(members) < 2L) {
      next
    }
    group_index <- group_index + 1L
    rows[[length(rows) + 1L]] <- data.frame(
      gene_id = gene_id,
      step_id = as.character(step_id),
      merge_group_id = sprintf("MG%02d", group_index),
      expected_fused_length = .oracle_format_length(
        state$edges$branch_length[row_index]
      ),
      group_size = as.character(length(members)),
      benchmark_unrooted_members = paste(members, collapse = "|"),
      stringsAsFactors = FALSE
    )
  }

  if (length(rows) == 0L) {
    return(data.frame(
      gene_id = character(),
      step_id = character(),
      merge_group_id = character(),
      expected_fused_length = character(),
      group_size = character(),
      benchmark_unrooted_members = character(),
      stringsAsFactors = FALSE
    ))
  }
  out <- do.call(rbind, rows)
  rownames(out) <- NULL
  out
}

#' Recompute the Catnip10 graph oracle
#'
#' Recompute a bundled Catnip10 deletion scenario with the independent pure R
#' node-edge oracle. The implementation tracks primitive edge membership through
#' explicit tip deletion and degree-2 contraction. It does not call the C++
#' production core and does not use projected splits to classify `NA_struct` or
#' `NA_fuse`.
#'
#' @param regime Deletion regime: `"global"` or `"local"`.
#' @return A list containing `matrix`, `status_long`, `fusion_groups`, and
#'   `deletion_order`, with the same schemas as the corresponding bundled frozen
#'   Catnip10 objects.
#' @examples
#' rebuilt <- recompute_catnip10_oracle("global")
#' identical(rebuilt$matrix, catnip10_matrix("global"))
#' @export
recompute_catnip10_oracle <- function(regime = c("global", "local")) {
  regime <- match.arg(regime)
  tree <- ape::read.tree(text = catnip10_oracle$species_tree)
  if (inherits(tree, "multiPhylo") || !inherits(tree, "phylo")) {
    stop("Bundled Catnip10 input must contain exactly one tree.", call. = FALSE)
  }

  frozen <- .oracle_freeze_tree_identity(tree)
  identity <- frozen$identity
  state <- .oracle_init_state(identity, frozen$root_label)
  axis <- as.character(identity$branch_id)
  deletion_order <- as.character(
    catnip10_oracle[[regime]]$deletion_order
  )

  matrix_rows <- list()
  status_rows <- list()
  fusion_rows <- list()

  for (step_id in 0:length(deletion_order)) {
    if (step_id > 0L) {
      state <- .oracle_delete_tip(state, deletion_order[step_id])
    }
    gene_id <- paste0("main_step", step_id)
    values <- .oracle_classify_state(state, identity)
    matrix_rows[[length(matrix_rows) + 1L]] <- unname(values[axis])

    status <- ifelse(
      values == "NA_struct", "NA_struct",
      ifelse(values == "NA_fuse", "NA_fuse", "observed")
    )
    status_rows[[length(status_rows) + 1L]] <- data.frame(
      gene_id = gene_id,
      step_id = as.character(step_id),
      branch_id = axis,
      value = unname(values[axis]),
      status = unname(status[axis]),
      tree_semantics = "unrooted",
      stringsAsFactors = FALSE
    )

    one_fusion <- .oracle_fusion_rows(state, gene_id, step_id)
    if (nrow(one_fusion) > 0L) {
      fusion_rows[[length(fusion_rows) + 1L]] <- one_fusion
    }
  }

  matrix_values <- as.data.frame(
    do.call(rbind, matrix_rows),
    stringsAsFactors = FALSE,
    check.names = FALSE
  )
  names(matrix_values) <- axis
  matrix_values[] <- lapply(matrix_values, as.character)
  matrix_out <- data.frame(
    gene_id = paste0("main_step", 0:length(deletion_order)),
    matrix_values,
    stringsAsFactors = FALSE,
    check.names = FALSE
  )
  status_out <- do.call(rbind, status_rows)
  rownames(status_out) <- NULL

  fusion_out <- if (length(fusion_rows) == 0L) {
    .oracle_fusion_rows(state, "", 0L)[0, , drop = FALSE]
  } else {
    do.call(rbind, fusion_rows)
  }
  rownames(fusion_out) <- NULL

  list(
    matrix = matrix_out,
    status_long = status_out,
    fusion_groups = fusion_out,
    deletion_order = deletion_order
  )
}
