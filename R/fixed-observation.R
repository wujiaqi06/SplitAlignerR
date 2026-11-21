# S4 v1 keeps S3 identity and normalized empirical observations separate.
# This assembler never passes joint observations to the S3 component assembler.

.s4_reference_table <- function(components, gene_id) {
  data.frame(gene_id = rep.int(gene_id, length(components)),
    coordinate_id = vapply(components, function(x)
      .s4_component_id(x$primitive_members), character(1)),
    primitive_members = I(lapply(components, `[[`, "primitive_members")),
    reference_source_nodes = I(lapply(components, `[[`, "reference_source_nodes")),
    stringsAsFactors = FALSE)
}

.s4_observation_table <- function(observations, gene_id) {
  data.frame(gene_id = rep.int(gene_id, length(observations)),
    observation_id = vapply(observations, function(x)
      paste0("O[", paste(x$primitive_members, collapse = "|"), "]"), character(1)),
    relation = vapply(observations, function(x)
      if (length(x$reference_component_ids) == 1L) "individual" else "joint",
      character(1)),
    reference_component_ids = I(lapply(observations, `[[`, "reference_component_ids")),
    primitive_members = I(lapply(observations, `[[`, "primitive_members")),
    input_edge_ids = I(lapply(observations, `[[`, "source_nodes")),
    source_lengths = I(lapply(observations, `[[`, "source_lengths")),
    source_status = I(lapply(observations, `[[`, "source_status")),
    normalization_mode = vapply(observations, `[[`, character(1), "normalization_mode"),
    numeric_status = vapply(observations, `[[`, character(1), "numeric_status"),
    numeric_value = vapply(observations, `[[`, numeric(1), "numeric_value"),
    stringsAsFactors = FALSE)
}

.s4_member_index <- function(members, axis) {
  positions <- match(unlist(members, use.names = FALSE), axis)
  if (any(lengths(members) == 0L) || anyNA(positions) || anyDuplicated(positions))
    stop("Internal S4 error: component or observation members are not disjoint.", call. = FALSE)
  owners <- integer(length(axis))
  owners[positions] <- rep.int(seq_along(members), lengths(members))
  list(owners = owners, sizes = lengths(members))
}

# The same two-cover gate is used for primitive and composite values.
.s4_observation_cell <- function(target, reference_index, observation_index,
                                 observations, view, details = TRUE,
                                 empty_sources = NULL) {
  ref_owners <- reference_index$owners[target]
  ref_touched <- sort(unique(ref_owners[ref_owners > 0L]))
  deleted <- any(ref_owners == 0L)
  partial_ref <- sum(reference_index$sizes[ref_touched]) > sum(ref_owners > 0L)
  ref_available <- !deleted && !partial_ref
  ref_state <- if (!ref_available) "unavailable" else
    if (length(ref_touched) == 1L) "active" else "decomposable"
  ref_reason <- if (deleted && partial_ref) "deleted_member_and_partial_component" else
    if (deleted) "deleted_member" else if (partial_ref) "partial_component" else "representable"
  out <- list(reference_state = ref_state, reference_reason = ref_reason,
    observation_status = "not_applicable", observation_reason = "reference_unavailable",
    numeric_status = "reference_unavailable", numeric_value = NA_real_,
    construction_mode = "none", observation_ids = character(),
    sources = NULL)
  if (!ref_available) {
    if (details) out$sources <- if (is.null(empty_sources))
      observations[integer(), , drop = FALSE] else empty_sources
    return(out)
  }

  obs_owners <- observation_index$owners[target]
  touched <- sort(unique(obs_owners[obs_owners > 0L]))
  unrepresented <- any(obs_owners == 0L)
  partial_obs <- sum(observation_index$sizes[touched]) > sum(obs_owners > 0L)
  # Primitive matrix assembly needs only the scalar result. Avoid creating a
  # source data.frame that would immediately be discarded for every primitive.
  # Detailed fusion records retain the same ordinary data.frame schema.
  if (details) out$sources <- if (!length(touched) && !is.null(empty_sources))
    empty_sources else observations[touched, , drop = FALSE]
  if (unrepresented || partial_obs) {
    out$observation_status <- "unavailable"
    out$observation_reason <- if (unrepresented && partial_obs)
      "unrepresented_and_partial_observation" else if (unrepresented)
      "unrepresented" else "partial_observation"
    out$numeric_status <- "observation_unavailable"
    return(out)
  }
  out$observation_ids <- observations$observation_id[touched]
  out$observation_reason <- "represented"
  single <- length(touched) == 1L
  out$observation_status <- if (single) "single_observation" else "multiple_observations"
  out$construction_mode <- if (single) "single_observation_lookup" else
    "selected_observation_unit_sum"
  # Uniqueness is local to this target, never enforced across global columns.
  inputs <- unlist(observations$input_edge_ids[touched], use.names = FALSE)
  if (anyDuplicated(inputs))
    stop("Internal S4 error: an input edge contributes twice to one target.", call. = FALSE)
  if (!single && view == "direct") {
    out$numeric_status <- "direct_only"
  } else if (any(observations$numeric_status[touched] == "software_failure_marker")) {
    out$numeric_status <- "software_failure_marker"
  } else if (any(!is.finite(observations$numeric_value[touched]))) {
    out$numeric_status <- "missing_branch_length"
  } else {
    values <- observations$numeric_value[touched]
    value <- if (single) values[[1L]] else sum(values[order(abs(values), values)])
    out$numeric_status <- if (is.finite(value)) "available" else "nonfinite_sum"
    if (is.finite(value)) out$numeric_value <- value
  }
  out
}

.s4_assemble_observations <- function(reference, prepared, observed, ids, outcomes, view) {
  primitive <- reference$primitives
  primitive$coordinate_id <- primitive$branch_id
  primitive$primitive_aliases <- primitive$aliases
  primitive$primitive_alias_text <- vapply(primitive$aliases, paste,
                                           character(1), collapse = "|")
  primitive$branch_id <- primitive$aliases <- NULL
  axis <- primitive$coordinate_id
  n <- length(ids)
  states <- matrix("NA_struct", n, length(axis), dimnames = list(ids, axis))
  ref_tables <- ref_indices <- vector("list", n)
  for (i in seq_along(ids)) {
    components <- prepared[[i]]$reference_components
    ref_tables[[i]] <- .s4_reference_table(components, ids[[i]])
    ref_indices[[i]] <- .s4_member_index(ref_tables[[i]]$primitive_members, axis)
    owner <- ref_indices[[i]]$owners
    kept <- which(owner > 0L)
    states[i, kept] <- ifelse(ref_indices[[i]]$sizes[owner[kept]] == 1L,
                             "observed", "NA_fuse")
  }
  references <- do.call(rbind, ref_tables)
  rownames(references) <- NULL
  # The shared deletion-fusion axis comes from ALL input reference restrictions,
  # including topology-skipped genes. It never comes from observation merging.
  fused <- references[lengths(references$primitive_members) > 1L, , drop = FALSE]
  fused <- fused[!duplicated(fused$coordinate_id), , drop = FALSE]
  if (nrow(fused)) {
    width <- nchar(as.character(length(axis)))
    keys <- vapply(fused$primitive_members, function(m)
      paste(sprintf(paste0("%0", width, "d"), match(m, axis)), collapse = ":"), character(1))
    fused <- fused[order(keys, method = "radix"), , drop = FALSE]
  }
  definitions <- data.frame(coordinate_id = fused$coordinate_id,
    coordinate_type = rep("composite", nrow(fused)),
    member_count = lengths(fused$primitive_members),
    member_text = vapply(fused$primitive_members, paste, character(1), collapse = "|"),
    primitive_members = I(as.list(fused$primitive_members)), stringsAsFactors = FALSE)
  rownames(definitions) <- NULL

  success <- which(outcomes$outcome == "success")
  kept_ids <- ids[success]
  pmat <- matrix(NA_real_, length(success), length(axis), dimnames = list(kept_ids, axis))
  fmat <- matrix(NA_real_, length(success), nrow(definitions),
                 dimnames = list(kept_ids, definitions$coordinate_id))
  relations <- matrix("NA_struct", length(success), length(axis), dimnames = dimnames(pmat))
  observation_ids <- matrix(NA_character_, length(success), length(axis), dimnames = dimnames(pmat))
  numeric_status <- matrix("reference_unavailable", length(success), length(axis), dimnames = dimnames(pmat))
  obs_tables <- obs_indices <- correspondence <- vector("list", length(success))
  for (k in seq_along(success)) {
    i <- success[[k]]
    obs <- .s4_observation_table(observed[[i]], ids[[i]])
    obs_tables[[k]] <- obs
    obs_indices[[k]] <- .s4_member_index(obs$primitive_members, axis)
    refs <- ref_tables[[i]]
    link <- integer(nrow(refs))
    for (o in seq_len(nrow(obs))) {
      touched <- match(obs$reference_component_ids[[o]], refs$coordinate_id)
      if (anyNA(touched) || any(link[touched] != 0L))
        stop("Internal S4 error: invalid observation-to-reference correspondence.", call. = FALSE)
      link[touched] <- o
    }
    relation <- rep("unrepresented", nrow(refs))
    oid <- rep(NA_character_, nrow(refs))
    represented <- which(link > 0L)
    relation[represented] <- obs$relation[link[represented]]
    oid[represented] <- obs$observation_id[link[represented]]
    correspondence[[k]] <- data.frame(gene_id = rep(ids[[i]], nrow(refs)),
      coordinate_id = refs$coordinate_id, observation_id = oid, relation = relation,
      representation_reason = ifelse(relation == "unrepresented", "ancestral_stem_outside_unrooted_view",
        ifelse(relation == "joint", "unrooted_suppression", "represented")),
      stringsAsFactors = FALSE)
    owner <- ref_indices[[i]]$owners
    present <- which(owner > 0L)
    relations[k, present] <- relation[owner[present]]
    observation_ids[k, present] <- oid[owner[present]]
    for (j in seq_along(axis)) {
      cell <- .s4_observation_cell(j, ref_indices[[i]], obs_indices[[k]], obs, view,
                                    details = FALSE)
      pmat[k, j] <- cell$numeric_value
      numeric_status[k, j] <- cell$numeric_status
    }
  }
  component_observations <- if (length(success)) do.call(rbind, correspondence) else
    data.frame(gene_id = character(), coordinate_id = character(), observation_id = character(),
      relation = character(), representation_reason = character(), stringsAsFactors = FALSE)
  rownames(component_observations) <- NULL
  # Only the combined reference and correspondence tables are returned. Their
  # temporary per-gene containers are no longer needed by fusion assembly.
  rm(ref_tables, correspondence)
  count <- length(success) * nrow(definitions)
  # Fill the final ledger columns directly, rather than keeping one nine-field
  # cell list per gene/column and then copying its fields to these vectors.
  cell_reference_state <- cell_reference_reason <- character(count)
  cell_observation_status <- cell_observation_reason <- character(count)
  cell_numeric_status <- cell_construction_mode <- character(count)
  cell_observation_ids <- cell_sources <- vector("list", count)
  empty_sources <- .s4_observation_table(list(), character())
  row <- 0L
  for (j in seq_len(nrow(definitions))) {
    target <- match(definitions$primitive_members[[j]], axis)
    for (k in seq_along(success)) {
      i <- success[[k]]
      cell <- .s4_observation_cell(target, ref_indices[[i]], obs_indices[[k]],
                                    obs_tables[[k]], view, empty_sources = empty_sources)
      fmat[k, j] <- cell$numeric_value
      row <- row + 1L
      cell_reference_state[[row]] <- cell$reference_state
      cell_reference_reason[[row]] <- cell$reference_reason
      cell_observation_status[[row]] <- cell$observation_status
      cell_observation_reason[[row]] <- cell$observation_reason
      cell_numeric_status[[row]] <- cell$numeric_status
      cell_construction_mode[[row]] <- cell$construction_mode
      cell_observation_ids[[row]] <- cell$observation_ids
      cell_sources[[row]] <- cell$sources
    }
  }
  # Matrix column order is precisely the public gene-within-fusion ledger order.
  values <- as.vector(fmat)
  fusion_ledger <- data.frame(gene_id = rep(kept_ids, times = nrow(definitions)),
    composite_id = rep(definitions$coordinate_id, each = length(success)),
    reference_state = cell_reference_state,
    reference_reason = cell_reference_reason,
    observation_status = cell_observation_status,
    observation_reason = cell_observation_reason,
    numeric_status = cell_numeric_status,
    numeric_available = is.finite(values), numeric_value = values,
    construction_mode = cell_construction_mode,
    observation_ids = I(cell_observation_ids),
    sources = I(cell_sources), stringsAsFactors = FALSE)
  # Delay the full observation-table concatenation until the temporary cell
  # work is finished; the per-gene tables remain sufficient for every lookup.
  obs_ledger <- if (length(success)) do.call(rbind, obs_tables) else empty_sources
  rownames(obs_ledger) <- NULL
  rm(obs_tables)
  list(reference_state_matrix = states, primitive_matrix = pmat, fusion_matrix = fmat,
    numeric_matrix = cbind(pmat, fmat), primitive_coordinates = primitive,
    composite_coordinates = definitions, reference_components = references,
    observation_ledger = obs_ledger, component_observations = component_observations,
    primitive_observation_matrix = relations, primitive_observation_id_matrix = observation_ids,
    primitive_numeric_status_matrix = numeric_status, fusion_ledger = fusion_ledger,
    gene_outcomes = outcomes,
    gene_provenance = data.frame(gene_id = ids,
      retained_taxa = I(lapply(prepared, `[[`, "retained_taxa")), stringsAsFactors = FALSE))
}
