## ARCH000A bounded truth-store streaming recovery engine.

a_make_catalog <- function(registry, authority, path,
                           bstar_threshold_bytes = 32 * 1024^2) {
  write_result <- a_write_packed_store(
    path, registry, authority,
    bstar_threshold_bytes = bstar_threshold_bytes
  )
  a_assert(write_result$roundtrip_all_equal, "Packed plan round-trip differs.")
  bstar_members <- write_result$bstar_members
  composite_ids <- vapply(bstar_members, function(members) {
    paste0("F[", paste(authority$primitive_id[members], collapse = "|"), "]")
  }, character(1))
  list(
    registry = registry,
    authority = authority,
    path = path,
    bstar_keys = write_result$bstar_keys,
    bstar_members = bstar_members,
    composite_ids = composite_ids,
    write_result = write_result
  )
}

a_measure_raw_read <- function(input) {
  started <- proc.time()[["elapsed"]]
  bytes <- records <- 0L
  if (is.character(input) && length(input) == 1L && file.exists(input)) {
    con <- if (grepl("[.]gz$", input, ignore.case = TRUE)) {
      gzfile(input, open = "rt", encoding = "UTF-8")
    } else {
      file(input, open = "rt", encoding = "UTF-8")
    }
    on.exit(close(con), add = TRUE)
    repeat {
      line <- readLines(con, n = 1L, warn = FALSE)
      if (!length(line)) break
      bytes <- bytes + nchar(line, type = "bytes") + 1L
      records <- records + 1L
    }
  } else if (is.character(input)) {
    bytes <- sum(nchar(input, type = "bytes") + 1L)
    records <- length(input)
  } else {
    a_stop("Raw-read measurement requires file or character records.")
  }
  list(
    seconds = unname(proc.time()[["elapsed"]] - started),
    bytes = as.numeric(bytes),
    physical_records = records
  )
}

a_split_index_from_tree <- function(tree, authority) {
  splits <- phangorn::as.splits(tree)
  labels <- enc2utf8(attr(splits, "labels"))
  quoted <- nchar(labels) >= 2L & startsWith(labels, "'") & endsWith(labels, "'")
  labels[quoted] <- gsub(
    "''", "'", substr(labels[quoted], 2L, nchar(labels[quoted]) - 1L),
    fixed = TRUE
  )
  ids_by_local_tip <- unname(authority$taxon_id[labels])
  if (anyNA(ids_by_local_tip)) a_stop("Recovery tree contains an unknown taxon.")
  retained <- sort(as.integer(ids_by_local_tip), method = "radix")
  weights <- attr(splits, "weights")
  if (is.null(weights)) weights <- rep(NA_real_, length(splits))
  keys <- character()
  values <- numeric()
  for (i in seq_along(splits)) {
    side <- sort(as.integer(ids_by_local_tip[splits[[i]]]), method = "radix")
    if (!length(side) || length(side) == length(retained)) next
    keys <- c(keys, arch_split_key(side, retained))
    values <- c(values, as.numeric(weights[[i]]))
  }
  unique_keys <- sort(unique(keys), method = "radix")
  grouped <- split(values, factor(keys, levels = unique_keys), drop = TRUE)
  combined <- vapply(grouped, function(one) {
    if (!length(one) || anyNA(one) || any(!is.finite(one))) NA_real_ else sum(one)
  }, numeric(1))
  list(keys = names(combined), values = unname(combined), retained_ids = retained)
}

a_query_truth_plan <- function(plan, empirical, authority,
                               bstar_keys, bstar_index) {
  b <- authority$primitive_count
  k <- length(bstar_keys)
  if (!identical(empirical$retained_ids, plan$retained_ids)) {
    a_stop("Empirical retained taxa differ from truth-plan identity.")
  }
  row_state <- plan$state_template
  eligible <- plan$eligible
  match_index <- match(plan$projected_split[eligible], empirical$keys)
  recovered <- !is.na(match_index)
  row_state[eligible[!recovered]] <- 3L
  row_state[eligible[recovered]] <- 0L
  terminal <- which(authority$branch_type == "terminal")
  if (any(row_state[terminal] == 3L)) {
    a_stop("Terminal NA_topo invariant failed.")
  }
  numeric <- rep(NA_real_, b + k)
  fused_by_primitive <- rep(NA_real_, b)
  if (any(recovered)) {
    targets <- eligible[recovered]
    numeric[targets] <- empirical$values[match_index[recovered]]
  }
  if (length(plan$composites)) {
    for (composite in plan$composites) {
      hit <- match(composite$projected_split, empirical$keys)
      if (!is.na(hit)) {
        column <- bstar_index[[composite$key]]
        numeric[[column]] <- empirical$values[[hit]]
        fused_by_primitive[composite$members] <- empirical$values[[hit]]
      }
    }
  }
  list(
    state = row_state,
    numeric = numeric,
    fused_by_primitive = fused_by_primitive,
    terminal_na_topo = sum(row_state[terminal] == 3L)
  )
}

a_checksum_row <- function(gene_id, state, numeric) {
  numeric_raw <- writeBin(as.double(numeric), raw(), size = 8L, endian = "little")
  a_adler32(c(charToRaw(enc2utf8(gene_id)), as.raw(state), numeric_raw))
}

a_process_with_store <- function(input, mapping, catalog, store,
                                 output_mode = c("sink", "compact"),
                                 dataset_label = "dataset") {
  output_mode <- match.arg(output_mode)
  authority <- catalog$authority
  b <- authority$primitive_count
  k <- length(catalog$bstar_keys)
  n <- nrow(mapping)
  a_assert(n > 0L, "Processing mapping is empty.")
  a_assert(!anyDuplicated(mapping$gene_id), "Processing mapping has duplicate IDs.")
  bstar_index <- stats::setNames(seq_along(catalog$bstar_keys) + b,
                                 catalog$bstar_keys)
  phase <- c(
    raw_read = 0, full_newick_parse = 0, empirical_split_index = 0,
    truth_plan_load = 0, deterministic_split_queries = 0,
    matrix_or_sink_write = 0, branch_counter_update = 0
  )
  raw_read <- a_measure_raw_read(input)
  phase[["raw_read"]] <- raw_read$seconds
  internal <- which(authority$branch_type == "internal")
  mapped_count <- integer(b)
  topo_count <- integer(b)
  terminal_na_topo <- 0L
  row_checksums <- character(n)
  state_matrix <- numeric_matrix <- fused_matrix <- NULL
  if (output_mode == "compact") {
    state_matrix <- matrix(as.raw(255L), nrow = n, ncol = b)
    numeric_matrix <- matrix(NA_real_, nrow = n, ncol = b + k)
    fused_matrix <- matrix(NA_real_, nrow = n, ncol = b)
    dimnames(state_matrix) <- list(mapping$gene_id, authority$primitive_id)
    dimnames(numeric_matrix) <- list(
      mapping$gene_id, c(authority$primitive_id, catalog$composite_ids)
    )
    dimnames(fused_matrix) <- list(mapping$gene_id, authority$primitive_id)
  }
  started_total <- proc.time()[["elapsed"]]
  seen <- arch_iterate_records(input, function(record, index) {
    a_assert(
      identical(record$id, mapping$gene_id[[index]]),
      sprintf("Gene ID/order differs in pass 2 at row %d.", index)
    )
    timed <- a_elapsed(ape::read.tree(text = record$newick))
    tree <- timed$value
    phase[["full_newick_parse"]] <<- phase[["full_newick_parse"]] + timed$seconds
    if (inherits(tree, "multiPhylo") || !inherits(tree, "phylo")) {
      a_stop("Recovery pass requires exactly one gene tree.")
    }
    timed <- a_elapsed(a_split_index_from_tree(tree, authority))
    empirical <- timed$value
    phase[["empirical_split_index"]] <<-
      phase[["empirical_split_index"]] + timed$seconds
    timed <- a_elapsed(store$get(mapping$pattern_id[[index]]))
    plan <- timed$value
    phase[["truth_plan_load"]] <<- phase[["truth_plan_load"]] + timed$seconds
    timed <- a_elapsed(a_query_truth_plan(
      plan, empirical, authority, catalog$bstar_keys, bstar_index
    ))
    queried <- timed$value
    phase[["deterministic_split_queries"]] <<-
      phase[["deterministic_split_queries"]] + timed$seconds
    terminal_na_topo <<- terminal_na_topo + queried$terminal_na_topo
    timed <- a_elapsed({
      row_checksums[[index]] <<- a_checksum_row(
        record$id, queried$state, queried$numeric
      )
      if (output_mode == "compact") {
        state_matrix[index, ] <<- as.raw(queried$state)
        numeric_matrix[index, ] <<- queried$numeric
        fused_matrix[index, ] <<- queried$fused_by_primitive
      }
    })
    phase[["matrix_or_sink_write"]] <<-
      phase[["matrix_or_sink_write"]] + timed$seconds
    timed <- a_elapsed({
      mapped_count[internal] <<- mapped_count[internal] +
        as.integer(queried$state[internal] == 0L)
      topo_count[internal] <<- topo_count[internal] +
        as.integer(queried$state[internal] == 3L)
    })
    phase[["branch_counter_update"]] <<-
      phase[["branch_counter_update"]] + timed$seconds
  })
  if (seen != n) a_stop("Pass-2 record count differs from gene mapping.")
  total_seconds <- unname(proc.time()[["elapsed"]] - started_total)
  normalized <- order(mapping$gene_id, method = "radix")
  normalized_checksum <- a_adler32(charToRaw(paste0(
    mapping$gene_id[normalized], ":", row_checksums[normalized], collapse = "\n"
  )))
  denominator <- mapped_count[internal] + topo_count[internal]
  support <- ifelse(
    denominator > 0L, mapped_count[internal] / denominator, NA_real_
  )
  result <- list(
    dataset_label = dataset_label,
    output_mode = output_mode,
    normalized_scientific_checksum = normalized_checksum,
    row_checksums = data.frame(
      gene_id = mapping$gene_id,
      checksum = row_checksums,
      stringsAsFactors = FALSE
    ),
    state_matrix = state_matrix,
    numeric_matrix = numeric_matrix,
    fused_numeric_by_primitive = fused_matrix,
    internal_counts = data.frame(
      coordinate_id = authority$primitive_id[internal],
      mapped_count = mapped_count[internal],
      NA_topo_count = topo_count[internal],
      support = support,
      stringsAsFactors = FALSE
    ),
    terminal_na_topo_count = terminal_na_topo,
    phase_seconds = phase,
    total_processing_seconds = total_seconds,
    raw_read_bytes = raw_read$bytes,
    store_stats = store$stats(),
    result_object_bytes = NA_real_
  )
  result$result_object_bytes <- as.numeric(object.size(result))
  class(result) <- c("arch000a_store_result", "list")
  result
}

a_paired_final_tokens <- function(fixed, free) {
  a_assert(
    identical(dimnames(fixed$state_matrix), dimnames(free$state_matrix)),
    "Paired bounded-store results require identical primitive axes."
  )
  fixed_state <- matrix(
    as.integer(fixed$state_matrix), nrow = nrow(fixed$state_matrix),
    dimnames = dimnames(fixed$state_matrix)
  )
  free_state <- matrix(
    as.integer(free$state_matrix), nrow = nrow(free$state_matrix),
    dimnames = dimnames(free$state_matrix)
  )
  b <- ncol(fixed_state)
  fixed_primitive <- fixed$numeric_matrix[, seq_len(b), drop = FALSE]
  free_primitive <- free$numeric_matrix[, seq_len(b), drop = FALSE]
  fixed_fused <- fixed$fused_numeric_by_primitive
  free_fused <- free$fused_numeric_by_primitive
  final <- matrix("NA", nrow = nrow(fixed_state), ncol = b,
                  dimnames = dimnames(fixed_state))
  mapped <- free_state == 0L & is.finite(free_primitive)
  final[mapped] <- trimws(formatC(
    free_primitive[mapped], digits = 17L, format = "g", decimal.mark = "."
  ))
  final[free_state == 1L] <- "NA_struct"
  fused <- free_state == 2L & is.finite(free_fused)
  final[fused] <- "NA_fuse"
  topo <- free_state == 3L & fixed_state == 0L & is.finite(fixed_primitive)
  final[topo] <- "NA_topo"
  fixed_final <- matrix("NA", nrow = nrow(fixed_state), ncol = b,
                        dimnames = dimnames(fixed_state))
  fixed_mapped <- fixed_state == 0L & is.finite(fixed_primitive)
  fixed_final[fixed_mapped] <- trimws(formatC(
    fixed_primitive[fixed_mapped], digits = 17L, format = "g", decimal.mark = "."
  ))
  fixed_final[fixed_state == 1L] <- "NA_struct"
  fixed_final[fixed_state == 2L & is.finite(fixed_fused)] <- "NA_fuse"
  list(fixed = fixed_final, final = final)
}

a_first_pass_cost_decomposition <- function(input, authority) {
  phase <- c(
    raw_sequential_read = 0, tree_boundary_detection = 0,
    tip_label_tokenization = 0, taxon_name_to_id = 0,
    exact_pattern_key = 0, pattern_registry_lookup = 0,
    truth_plan_construction = 0, bstar_emission = 0,
    bstar_local_dedup = 0, bstar_global_union = 0
  )
  timed <- a_elapsed({
    if (is.character(input) && length(input) == 1L && file.exists(input)) {
      readLines(input, warn = FALSE, encoding = "UTF-8")
    } else input
  })
  lines <- timed$value
  phase[["raw_sequential_read"]] <- timed$seconds
  timed <- a_elapsed({
    records <- lapply(seq_along(lines), function(i) arch_parse_record(lines[[i]], i))
    Filter(Negate(is.null), records)
  })
  records <- timed$value
  phase[["tree_boundary_detection"]] <- timed$seconds
  timed <- a_elapsed(lapply(records, function(x) arch_scan_tips(x$newick)))
  taxa <- timed$value
  phase[["tip_label_tokenization"]] <- timed$seconds
  timed <- a_elapsed(lapply(taxa, arch_taxa_to_ids, authority = authority))
  retained <- timed$value
  phase[["taxon_name_to_id"]] <- timed$seconds
  timed <- a_elapsed(lapply(retained, function(ids) {
    bits <- a_pack_ids(ids, length(authority$taxa))
    list(bits = bits, key = a_pattern_exact_key(bits))
  }))
  packed <- timed$value
  phase[["exact_pattern_key"]] <- timed$seconds
  timed <- a_elapsed({
    seen <- new.env(hash = TRUE, parent = emptyenv())
    for (item in packed) {
      if (!exists(item$key, seen, inherits = FALSE)) {
        assign(item$key, item$bits, seen)
      }
    }
    keys <- sort(ls(seen, all.names = TRUE), method = "radix")
    lapply(keys, get, envir = seen, inherits = FALSE)
  })
  unique_bits <- timed$value
  phase[["pattern_registry_lookup"]] <- timed$seconds
  composites <- vector("list", length(unique_bits))
  timed <- a_elapsed({
    plans <- lapply(unique_bits, function(bits) {
      arch_build_truth_plan(
        authority, a_unpack_ids(bits, length(authority$taxa))
      )
    })
  })
  plans <- timed$value
  phase[["truth_plan_construction"]] <- timed$seconds
  timed <- a_elapsed({
    emitted <- unlist(lapply(plans, function(plan) {
      if (!length(plan$composites)) character() else names(plan$composites)
    }), use.names = FALSE)
  })
  emitted <- timed$value
  phase[["bstar_emission"]] <- timed$seconds
  timed <- a_elapsed({
    chunks <- split(emitted, ceiling(seq_along(emitted) / 1024L))
    local <- lapply(chunks, function(x) sort(unique(x), method = "radix"))
  })
  local <- timed$value
  phase[["bstar_local_dedup"]] <- timed$seconds
  timed <- a_elapsed({
    global <- character()
    for (chunk in local) global <- arch_merge_sorted_unique(global, chunk)
    global
  })
  global <- timed$value
  phase[["bstar_global_union"]] <- timed$seconds
  list(
    phase_seconds = phase,
    locus_count = length(records),
    unique_patterns = length(unique_bits),
    unique_bstar = length(global),
    decomposition_kind = "isolated repeated-phase measurement"
  )
}
