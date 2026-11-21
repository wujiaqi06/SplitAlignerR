# S4 keeps the S3 reference restriction separate from the structure represented
# by a gene input. Graph surgery below only changes fresh matching views.

.s4_prepare_observation <- function(reference, parsed, gene_id) {
  gene <- .s4_graph(parsed, gene_id = gene_id)
  retained <- gene$labels[gene$tip]
  unknown <- setdiff(enc2utf8(retained), enc2utf8(reference$taxa))
  if (length(unknown)) {
    .s4_stop(paste0("Gene tree contains taxa absent from the reference: ",
                    paste(unknown, collapse = ", "), "."), gene_id,
             code = "UNKNOWN_TAXON")
  }
  retained <- retained[order(vapply(retained, .s4_byte_key, character(1)),
                              method = "radix")]
  # Each input edge has one raw parser address. Root annotations have no edge
  # and are intentionally absent from this graph and its provenance.
  raw_sources <- unlist(gene$sources, use.names = FALSE)
  if (any(lengths(gene$sources) != 1L) || anyNA(raw_sources) ||
      any(raw_sources < 0L) || anyDuplicated(raw_sources)) {
    .s4_stop("Malformed input-edge provenance.", gene_id)
  }
  ref <- list2env(reference$graph, parent = emptyenv())
  ref$gene_id <- gene_id
  .s4_prune(ref, retained, reference$semantics, root_policy = "preserve")
  axis <- reference$primitives$branch_id
  components <- lapply(which(ref$active), function(edge) {
    members <- ref$members[[edge]]
    members <- members[order(match(members, axis))]
    list(primitive_members = members,
         reference_source_nodes = sort(ref$sources[[edge]]))
  })
  positions <- vapply(components, function(component)
    min(match(component$primitive_members, axis)), integer(1))
  list(gene_id = gene_id, retained_taxa = retained,
       reference_components = components[order(positions)],
       reference_graph = .s4_snapshot(ref), gene_graph = .s4_snapshot(gene))
}

.s4_match_observation <- function(reference, prepared, gene_semantics) {
  gene_semantics <- match.arg(gene_semantics, c("unrooted", "reference_rooted"))
  if (gene_semantics == "reference_rooted" && reference$semantics != "rooted") {
    stop("`reference_rooted` gene inputs require a rooted reference.", call. = FALSE)
  }
  gene_id <- prepared$gene_id
  ref <- list2env(prepared$reference_graph, parent = emptyenv())
  gene <- list2env(prepared$gene_graph, parent = emptyenv())
  semantics <- if (gene_semantics == "unrooted") "unrooted" else "rooted"

  # Normalize structure first, then assess each complete observation's raw
  # lengths. A finite prefix may overflow although a later missing edge makes
  # the complete observation unavailable; contraction must not reject that
  # prefix or lose the individual source values and their status.
  raw_sources <- unlist(gene$sources, use.names = FALSE)
  raw_values <- gene$value
  raw_status <- gene$status
  gene$value[] <- NA_real_
  gene$status[] <- "missing_branch_length"
  .s4_normalize(ref, semantics, root_policy = "preserve")
  .s4_normalize(gene, semantics, root_policy = "preserve")
  if (semantics == "unrooted") {
    anchor <- prepared$retained_taxa[[1L]]
    ref_root <- which(ref$alive & ref$tip & ref$labels == anchor)
    gene_root <- which(gene$alive & gene$tip & gene$labels == anchor)
  } else {
    ref_root <- ref$root
    gene_root <- gene$root
  }
  ref_order <- .s4_orient(ref, ref_root, gene_id)
  gene_order <- .s4_orient(gene, gene_root, gene_id)
  intern <- new.env(hash = TRUE, parent = emptyenv())
  intern$.next_id <- 0L
  ref_sig <- .s4_signatures(ref, ref_order, intern)
  gene_sig <- .s4_signatures(gene, gene_order, intern)
  if (ref_sig[[ref_root]] != gene_sig[[gene_root]]) {
    root_note <- if (gene_semantics == "reference_rooted")
      paste0(" The reference_rooted declaration requires the original reference root",
             " and every required ancestral stem to be retained; a different root",
             " or an omitted stem also causes this mismatch.") else ""
    .s4_stop(paste0("Gene tree '", gene_id,
                    "' does not match the restricted reference topology (",
                    gene_semantics, ").", root_note), gene_id,
             code = "FIXED_TOPOLOGY_MISMATCH", mismatch = TRUE)
  }

  axis <- reference$primitives$branch_id
  components <- prepared$reference_components
  component_members <- lapply(components, `[[`, "primitive_members")
  component_sizes <- lengths(component_members)
  component_ids <- vapply(component_members, .s4_component_id, character(1))
  positions <- match(unlist(component_members, use.names = FALSE), axis)
  if (any(component_sizes == 0L) || anyNA(positions) || anyDuplicated(positions)) {
    stop("Internal S4 reference-component membership is invalid.", call. = FALSE)
  }
  owner <- integer(length(axis))
  owner[positions] <- rep.int(seq_along(components), component_sizes)
  observations <- vector("list", sum(ref$active))
  pairs <- list(c(ref_root, gene_root))
  next_pair <- 1L
  observation_index <- 0L
  while (next_pair <= length(pairs)) {
    pair <- pairs[[next_pair]]
    next_pair <- next_pair + 1L
    ref_children <- ref_order$children[[pair[[1L]]]]
    gene_children <- gene_order$children[[pair[[2L]]]]
    ref_children <- ref_children[order(ref_sig[ref_children])]
    gene_children <- gene_children[order(gene_sig[gene_children])]
    for (i in seq_along(ref_children)) {
      r <- ref_children[[i]]
      g <- gene_children[[i]]
      re <- ref_order$incoming[[r]]
      ge <- gene_order$incoming[[g]]
      members <- ref$members[[re]]
      member_positions <- match(members, axis)
      if (!length(members) || anyNA(member_positions) ||
          anyDuplicated(member_positions)) {
        stop("Internal S4 observation membership is invalid.", call. = FALSE)
      }
      members <- members[order(member_positions)]
      selected <- owner[sort(member_positions)]
      touched <- sort(unique(selected))
      if (any(selected == 0L) || sum(component_sizes[touched]) != length(members)) {
        stop("Internal S4 observation cuts a reference component.", call. = FALSE)
      }
      sources <- sort(gene$sources[[ge]])
      source_positions <- match(sources, raw_sources)
      if (!length(sources) || anyNA(source_positions) || anyDuplicated(sources)) {
        stop("Internal S4 observation source provenance is invalid.", call. = FALSE)
      }
      source_lengths <- raw_values[source_positions]
      source_status <- raw_status[source_positions]
      value <- NA_real_
      if (any(source_status == "software_failure_marker")) {
        status <- "software_failure_marker"
      } else if (any(source_status == "missing_branch_length")) {
        status <- "missing_branch_length"
      } else {
        # A different Newick display root or child order must not choose a
        # different addition order for the same complete set of raw lengths.
        addition_order <- order(abs(source_lengths), source_lengths,
                                method = "radix")
        value <- sum(source_lengths[addition_order])
        if (!is.finite(value)) {
          .s4_stop("Complete input-observation length sum exceeds the finite numeric range.",
                   gene_id, code = "NUMERIC_RANGE_ERROR")
        }
        status <- "finite_numeric"
      }
      observation_index <- observation_index + 1L
      observations[[observation_index]] <- list(
        primitive_members = members,
        reference_component_ids = component_ids[touched],
        source_nodes = sources, source_lengths = source_lengths,
        source_status = source_status, numeric_value = value,
        numeric_status = status,
        normalization_mode = if (length(sources) == 1L)
          "single_input_edge" else "input_edge_sum"
      )
      pairs[[length(pairs) + 1L]] <- c(r, g)
    }
  }
  observation_order <- order(vapply(observations, function(observation)
    min(match(observation$primitive_members, axis)), integer(1)))
  observations[observation_order]
}
