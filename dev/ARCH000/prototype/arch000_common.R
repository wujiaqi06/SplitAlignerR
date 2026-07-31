## ARCH000 development-only shared utilities.
##
## This file is deliberately outside the package runtime.  It prototypes the
## shared-truth streaming representation without changing exported functions
## or the certified mapper.

arch_stop <- function(...) stop(..., call. = FALSE)

arch_utf8_hex <- function(value) {
  value <- enc2utf8(value)
  vapply(value, function(one) {
    paste(sprintf("%02x", as.integer(charToRaw(one))), collapse = "")
  }, character(1), USE.NAMES = FALSE)
}

arch_byte_order <- function(value) {
  order(arch_utf8_hex(value), method = "radix")
}

arch_canonical_taxa <- function(value) {
  value <- enc2utf8(as.character(value))
  value[arch_byte_order(value)]
}

arch_pattern_key <- function(taxon_ids) {
  taxon_ids <- sort(unique(as.integer(taxon_ids)), method = "radix")
  paste0(
    "PT1:", sprintf("%08x", length(taxon_ids)), ":",
    paste(sprintf("%08x", taxon_ids), collapse = "")
  )
}

arch_member_key <- function(member_ids) {
  member_ids <- sort(unique(as.integer(member_ids)), method = "radix")
  if (length(member_ids) < 2L) {
    arch_stop("A dynamic B* coordinate requires at least two primitive members.")
  }
  paste0("BM1:", paste(sprintf("%08x", member_ids), collapse = "."))
}

arch_member_key_decode <- function(key) {
  if (!startsWith(key, "BM1:") || nchar(key, type = "bytes") < 21L) {
    arch_stop("Invalid ARCH000 B* member key.")
  }
  tokens <- strsplit(substr(key, 5L, nchar(key)), ".", fixed = TRUE)[[1L]]
  if (length(tokens) < 2L || any(nchar(tokens, type = "bytes") != 8L)) {
    arch_stop("Invalid ARCH000 B* member-key payload.")
  }
  vapply(tokens, strtoi, integer(1), base = 16L)
}

arch_split_key <- function(side_ids, retained_ids) {
  retained_ids <- sort(unique(as.integer(retained_ids)), method = "radix")
  side_a <- sort(unique(as.integer(side_ids)), method = "radix")
  side_b <- setdiff(retained_ids, side_a)
  if (!length(side_a) || !length(side_b)) {
    arch_stop("A canonical split requires two nonempty retained-taxon sides.")
  }
  encode <- function(ids) paste(sprintf("%08x", ids), collapse = "")
  key_a <- encode(side_a)
  key_b <- encode(side_b)
  chosen <- if (length(side_a) < length(side_b)) {
    side_a
  } else if (length(side_b) < length(side_a)) {
    side_b
  } else if (key_a <= key_b) {
    side_a
  } else {
    side_b
  }
  paste0(
    "SP1:", sprintf("%08x", length(retained_ids)), ":",
    sprintf("%08x", length(chosen)), ":", encode(chosen)
  )
}

arch_species_authority <- function(species_tree) {
  validated <- SplitAlignerR::validate_species_tree(species_tree)
  taxa <- arch_canonical_taxa(validated$tip_labels)
  taxon_id <- stats::setNames(seq_along(taxa), taxa)
  coordinates <- validated$coordinates
  side_ids <- function(values) {
    ids <- unname(taxon_id[enc2utf8(values)])
    if (anyNA(ids)) arch_stop("Species-coordinate side contains an unknown taxon.")
    sort(as.integer(ids), method = "radix")
  }
  list(
    validated = validated,
    taxa = taxa,
    taxon_id = taxon_id,
    primitive_id = as.character(coordinates$coordinate_id),
    branch_type = as.character(coordinates$branch_type),
    side_a = lapply(coordinates$side_a_taxa, side_ids),
    side_b = lapply(coordinates$side_b_taxa, side_ids),
    primitive_count = nrow(coordinates),
    coordinate_table = coordinates
  )
}

arch_parse_record <- function(line, record_number = NA_integer_) {
  line <- enc2utf8(trimws(line))
  if (!nzchar(line) || startsWith(line, "#")) return(NULL)
  first <- substr(line, 1L, 1L)
  embedded_id <- NA_character_
  newick <- line
  if (!first %in% c("(", "[")) {
    open <- regexpr("(", line, fixed = TRUE)[[1L]]
    if (open < 2L) {
      arch_stop(sprintf("Record %s has no Newick opening parenthesis.", record_number))
    }
    embedded_id <- trimws(substr(line, 1L, open - 1L))
    if (!grepl("^[A-Za-z0-9_.-]+$", embedded_id)) {
      arch_stop(sprintf("Record %s has an invalid ID prefix.", record_number))
    }
    newick <- substr(line, open, nchar(line))
  }
  list(id = embedded_id, newick = newick)
}

arch_skip_annotation <- function(bytes, start) {
  depth <- 0L
  i <- start
  n <- length(bytes)
  while (i <= n) {
    if (bytes[[i]] == 91L) depth <- depth + 1L
    if (bytes[[i]] == 93L) {
      depth <- depth - 1L
      if (depth == 0L) return(i + 1L)
    }
    i <- i + 1L
  }
  arch_stop("Unterminated Newick annotation block in taxa-only scan.")
}

arch_scan_tips <- function(newick) {
  bytes <- as.integer(charToRaw(enc2utf8(newick)))
  n <- length(bytes)
  whitespace <- c(9L, 10L, 11L, 12L, 13L, 32L)
  delimiters <- c(40L, 41L, 44L, 58L, 59L, 91L, 93L)
  tips <- character()
  expecting_tip <- FALSE
  i <- 1L
  while (i <= n) {
    byte <- bytes[[i]]
    if (byte %in% whitespace) {
      i <- i + 1L
      next
    }
    if (byte == 91L) {
      i <- arch_skip_annotation(bytes, i)
      next
    }
    if (byte == 40L || byte == 44L) {
      expecting_tip <- TRUE
      i <- i + 1L
      next
    }
    if (byte == 41L) {
      expecting_tip <- FALSE
      i <- i + 1L
      next
    }
    if (!expecting_tip) {
      i <- i + 1L
      next
    }

    if (byte == 39L) {
      i <- i + 1L
      label <- raw()
      closed <- FALSE
      while (i <= n) {
        if (bytes[[i]] == 39L) {
          if (i < n && bytes[[i + 1L]] == 39L) {
            label <- c(label, as.raw(39L))
            i <- i + 2L
            next
          }
          i <- i + 1L
          closed <- TRUE
          break
        }
        label <- c(label, as.raw(bytes[[i]]))
        i <- i + 1L
      }
      if (!closed) arch_stop("Unterminated quoted Newick tip label.")
      tips <- c(tips, rawToChar(label))
      expecting_tip <- FALSE
      next
    }

    start <- i
    while (i <= n && !bytes[[i]] %in% c(delimiters, whitespace)) {
      i <- i + 1L
    }
    if (i == start) {
      arch_stop("Taxa-only scan encountered an empty terminal label.")
    }
    tips <- c(tips, rawToChar(as.raw(bytes[start:(i - 1L)])))
    expecting_tip <- FALSE
  }
  tips <- enc2utf8(tips)
  if (length(tips) < 2L) arch_stop("A gene tree must retain at least two taxa.")
  if (anyDuplicated(tips)) arch_stop("Taxa-only scan found a duplicate tip label.")
  arch_canonical_taxa(tips)
}

arch_complete_parse_tips <- function(newick) {
  validated <- SplitAlignerR::validate_species_tree(newick)
  arch_canonical_taxa(validated$tip_labels)
}

arch_iterate_records <- function(input, callback, max_records = Inf) {
  count <- 0L
  process <- function(line, physical_index) {
    record <- arch_parse_record(line, physical_index)
    if (is.null(record)) return(TRUE)
    count <<- count + 1L
    record$id <- if (is.na(record$id) || !nzchar(record$id)) {
      sprintf("gene_%06d", count)
    } else {
      record$id
    }
    callback(record, count)
    count < max_records
  }

  if (is.character(input) && length(input) == 1L && file.exists(input)) {
    con <- if (grepl("[.]gz$", input, ignore.case = TRUE)) {
      gzfile(input, open = "rt", encoding = "UTF-8")
    } else {
      file(input, open = "rt", encoding = "UTF-8")
    }
    on.exit(close(con), add = TRUE)
    physical <- 0L
    repeat {
      line <- readLines(con, n = 1L, warn = FALSE)
      if (!length(line)) break
      physical <- physical + 1L
      if (!process(line, physical)) break
    }
  } else if (is.character(input)) {
    for (physical in seq_along(input)) {
      if (!process(input[[physical]], physical)) break
    }
  } else {
    arch_stop("ARCH000 prototype input must be a line-based file or character vector.")
  }
  count
}

arch_taxa_to_ids <- function(taxa, authority) {
  ids <- unname(authority$taxon_id[enc2utf8(taxa)])
  if (anyNA(ids)) {
    unknown <- taxa[is.na(ids)]
    arch_stop(sprintf(
      "Gene tree contains taxon absent from species tree: %s",
      paste(unknown, collapse = ", ")
    ))
  }
  sort(as.integer(ids), method = "radix")
}

arch_build_truth_plan <- function(authority, retained_ids) {
  retained_ids <- sort(unique(as.integer(retained_ids)), method = "radix")
  b <- authority$primitive_count
  state <- rep.int(0L, b)
  projected <- rep.int(NA_character_, b)
  side_a_size <- integer(b)
  side_b_size <- integer(b)
  for (i in seq_len(b)) {
    left <- intersect(authority$side_a[[i]], retained_ids)
    right <- intersect(authority$side_b[[i]], retained_ids)
    side_a_size[[i]] <- length(left)
    side_b_size[[i]] <- length(right)
    if (!length(left) || !length(right)) {
      state[[i]] <- 1L
    } else {
      projected[[i]] <- arch_split_key(left, retained_ids)
    }
  }
  active <- which(!is.na(projected))
  grouped <- split(active, projected[active], drop = TRUE)
  composites <- list()
  for (query in names(grouped)) {
    members <- sort(as.integer(grouped[[query]]), method = "radix")
    if (length(members) > 1L) {
      state[members] <- 2L
      key <- arch_member_key(members)
      composites[[key]] <- list(
        key = key,
        members = members,
        projected_split = query
      )
    } else {
      i <- members[[1L]]
      eligible <- authority$branch_type[[i]] == "terminal" ||
        (side_a_size[[i]] >= 2L && side_b_size[[i]] >= 2L)
      if (!eligible) {
        arch_stop(sprintf(
          "Truth-plan invariant failed for singleton primitive %s.",
          authority$primitive_id[[i]]
        ))
      }
    }
  }
  terminal <- which(authority$branch_type == "terminal")
  retained_terminal <- vapply(terminal, function(i) {
    length(intersect(authority$side_a[[i]], retained_ids)) > 0L &&
      length(intersect(authority$side_b[[i]], retained_ids)) > 0L
  }, logical(1))
  if (any(state[terminal[retained_terminal]] == 1L)) {
    arch_stop("Retained terminal coordinate was incorrectly classified NA_struct.")
  }
  list(
    pattern_key = arch_pattern_key(retained_ids),
    retained_ids = retained_ids,
    state_template = state,
    projected_split = projected,
    side_a_size = side_a_size,
    side_b_size = side_b_size,
    composites = composites,
    eligible = which(state == 0L),
    bytes = NA_real_
  )
}

arch_new_bstar_accumulator <- function(threshold_bytes = 32 * 1024^2) {
  stopifnot(length(threshold_bytes) == 1L, is.finite(threshold_bytes),
            threshold_bytes > 0)
  e <- new.env(parent = emptyenv())
  e$threshold_bytes <- as.numeric(threshold_bytes)
  e$pending <- character()
  e$global <- character()
  e$flush_count <- 0L
  e$peak_pending_bytes <- 0
  e$records_seen <- 0L
  class(e) <- "arch000_bstar_accumulator"
  e
}

arch_merge_sorted_unique <- function(left, right) {
  if (!length(left)) return(right)
  if (!length(right)) return(left)
  out <- character(length(left) + length(right))
  i <- j <- k <- 1L
  last <- NULL
  while (i <= length(left) || j <= length(right)) {
    take_left <- j > length(right) ||
      (i <= length(left) && left[[i]] <= right[[j]])
    value <- if (take_left) left[[i]] else right[[j]]
    if (take_left) i <- i + 1L else j <- j + 1L
    if (is.null(last) || !identical(value, last)) {
      out[[k]] <- value
      k <- k + 1L
      last <- value
    }
  }
  out[seq_len(k - 1L)]
}

arch_bstar_flush <- function(accumulator) {
  if (!length(accumulator$pending)) return(invisible(accumulator))
  local <- sort(unique(accumulator$pending), method = "radix")
  accumulator$global <- arch_merge_sorted_unique(accumulator$global, local)
  accumulator$pending <- character()
  accumulator$flush_count <- accumulator$flush_count + 1L
  invisible(accumulator)
}

arch_bstar_add <- function(accumulator, member_ids) {
  key <- arch_member_key(member_ids)
  accumulator$pending <- c(accumulator$pending, key)
  accumulator$records_seen <- accumulator$records_seen + 1L
  bytes <- as.numeric(object.size(accumulator$pending))
  accumulator$peak_pending_bytes <- max(accumulator$peak_pending_bytes, bytes)
  if (bytes >= accumulator$threshold_bytes) arch_bstar_flush(accumulator)
  invisible(key)
}

arch_bstar_finalize <- function(accumulator) {
  arch_bstar_flush(accumulator)
  accumulator$global
}

arch_exact_hash_bucket_dedup <- function(member_sets, hash_fn) {
  exact <- vapply(member_sets, arch_member_key, character(1))
  hash <- vapply(member_sets, hash_fn, character(1))
  buckets <- split(exact, hash, drop = TRUE)
  sort(unique(unlist(lapply(buckets, unique), use.names = FALSE)), method = "radix")
}

arch_first_pass <- function(species_tree, input,
                            method = c("taxa_scan", "full_parse"),
                            bstar_threshold_bytes = 32 * 1024^2) {
  method <- match.arg(method)
  authority <- arch_species_authority(species_tree)
  pattern_env <- new.env(hash = TRUE, parent = emptyenv())
  gene_ids <- character()
  gene_pattern_keys <- character()
  taxon_counts <- integer()
  bstar <- arch_new_bstar_accumulator(bstar_threshold_bytes)
  started <- proc.time()[["elapsed"]]
  count <- arch_iterate_records(input, function(record, index) {
    taxa <- if (method == "taxa_scan") {
      arch_scan_tips(record$newick)
    } else {
      arch_complete_parse_tips(record$newick)
    }
    retained <- arch_taxa_to_ids(taxa, authority)
    key <- arch_pattern_key(retained)
    gene_ids[[index]] <<- record$id
    gene_pattern_keys[[index]] <<- key
    taxon_counts[[index]] <<- length(retained)
    if (!exists(key, envir = pattern_env, inherits = FALSE)) {
      plan <- arch_build_truth_plan(authority, retained)
      plan$bytes <- as.numeric(object.size(plan))
      assign(key, plan, envir = pattern_env)
      if (length(plan$composites)) {
        for (composite in plan$composites) {
          arch_bstar_add(bstar, composite$members)
        }
      }
    }
  })
  elapsed <- proc.time()[["elapsed"]] - started
  if (!count) arch_stop("First pass found no gene-tree records.")
  if (anyDuplicated(gene_ids)) arch_stop("Duplicate gene identifiers are invalid.")

  pattern_keys <- sort(ls(pattern_env, all.names = TRUE), method = "radix")
  patterns <- lapply(pattern_keys, get, envir = pattern_env, inherits = FALSE)
  pattern_ids <- sprintf("P%08d", seq_along(pattern_keys))
  names(patterns) <- pattern_ids
  gene_to_pattern <- match(gene_pattern_keys, pattern_keys)
  bstar_keys <- arch_bstar_finalize(bstar)
  bstar_members <- lapply(bstar_keys, arch_member_key_decode)
  composite_ids <- vapply(bstar_members, function(members) {
    paste0("F[", paste(authority$primitive_id[members], collapse = "|"), "]")
  }, character(1))
  list(
    authority = authority,
    gene_ids = gene_ids,
    gene_to_pattern = as.integer(gene_to_pattern),
    taxon_counts = taxon_counts,
    patterns = patterns,
    pattern_keys = pattern_keys,
    pattern_ids = pattern_ids,
    bstar_keys = bstar_keys,
    bstar_members = bstar_members,
    composite_ids = composite_ids,
    bstar_accumulator = list(
      threshold_bytes = bstar$threshold_bytes,
      peak_pending_bytes = bstar$peak_pending_bytes,
      flush_count = bstar$flush_count,
      records_seen = bstar$records_seen
    ),
    method = method,
    elapsed = unname(elapsed),
    locus_count = count
  )
}

arch_empirical_split_index <- function(newick, authority) {
  tree <- ape::read.tree(text = newick)
  if (inherits(tree, "multiPhylo") || !inherits(tree, "phylo")) {
    arch_stop("Recovery pass requires exactly one parsed gene tree.")
  }
  splits <- phangorn::as.splits(tree)
  labels <- enc2utf8(attr(splits, "labels"))
  quoted <- nchar(labels) >= 2L & startsWith(labels, "'") &
    endsWith(labels, "'")
  labels[quoted] <- gsub(
    "''", "'", substr(labels[quoted], 2L, nchar(labels[quoted]) - 1L),
    fixed = TRUE
  )
  ids_by_local_tip <- unname(authority$taxon_id[labels])
  if (anyNA(ids_by_local_tip)) arch_stop("Recovery tree contains an unknown taxon.")
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

arch_state_labels <- c("mapped", "NA_struct", "NA_fuse", "NA_topo")

arch_decode_state_matrix <- function(state_matrix) {
  codes <- as.integer(state_matrix)
  output <- matrix(
    arch_state_labels[codes + 1L], nrow = nrow(state_matrix),
    dimnames = dimnames(state_matrix)
  )
  output
}

arch_stream_compact <- function(species_tree, input,
                                first_method = c("taxa_scan", "full_parse"),
                                bstar_threshold_bytes = 32 * 1024^2) {
  first_method <- match.arg(first_method)
  rss <- function() {
    if (!requireNamespace("ps", quietly = TRUE)) return(NA_real_)
    as.numeric(ps::ps_memory_info(ps::ps_handle())[["rss"]])
  }
  rss_samples <- c(start = rss())
  first <- arch_first_pass(
    species_tree, input, method = first_method,
    bstar_threshold_bytes = bstar_threshold_bytes
  )
  rss_samples <- c(rss_samples, after_first_pass = rss())
  n <- first$locus_count
  b <- first$authority$primitive_count
  k <- length(first$bstar_keys)
  state <- matrix(as.raw(255L), nrow = n, ncol = b)
  numeric <- matrix(NA_real_, nrow = n, ncol = b + k)
  dimnames(state) <- list(first$gene_ids, first$authority$primitive_id)
  dimnames(numeric) <- list(
    first$gene_ids,
    c(first$authority$primitive_id, first$composite_ids)
  )
  internal <- which(first$authority$branch_type == "internal")
  mapped_count <- integer(b)
  topo_count <- integer(b)
  bstar_col <- stats::setNames(seq_along(first$bstar_keys) + b, first$bstar_keys)
  started <- proc.time()[["elapsed"]]
  seen <- arch_iterate_records(input, function(record, index) {
    plan <- first$patterns[[first$gene_to_pattern[[index]]]]
    empirical <- arch_empirical_split_index(record$newick, first$authority)
    if (!identical(empirical$retained_ids, plan$retained_ids)) {
      arch_stop(sprintf("Pass-2 retained taxa changed for gene %s.", record$id))
    }
    row_state <- plan$state_template
    eligible <- plan$eligible
    match_index <- match(plan$projected_split[eligible], empirical$keys)
    recovered <- !is.na(match_index)
    row_state[eligible[!recovered]] <- 3L
    row_state[eligible[recovered]] <- 0L
    terminal <- which(first$authority$branch_type == "terminal")
    if (any(row_state[terminal] == 3L)) {
      arch_stop(sprintf("Terminal NA_topo invariant failed for gene %s.", record$id))
    }
    state[index, ] <<- as.raw(row_state)
    if (any(recovered)) {
      targets <- eligible[recovered]
      numeric[index, targets] <<- empirical$values[match_index[recovered]]
    }
    if (length(plan$composites)) {
      for (composite in plan$composites) {
        hit <- match(composite$projected_split, empirical$keys)
        if (!is.na(hit)) {
          numeric[index, bstar_col[[composite$key]]] <<- empirical$values[[hit]]
        }
      }
    }
    mapped_count[internal] <<- mapped_count[internal] +
      as.integer(row_state[internal] == 0L)
    topo_count[internal] <<- topo_count[internal] +
      as.integer(row_state[internal] == 3L)
  })
  second_elapsed <- proc.time()[["elapsed"]] - started
  if (seen != n) arch_stop("Pass-2 gene count differs from pass 1.")
  rss_samples <- c(rss_samples, after_second_pass = rss())
  support <- rep(NA_real_, b)
  denominator <- mapped_count[internal] + topo_count[internal]
  support[internal] <- ifelse(
    denominator > 0L, mapped_count[internal] / denominator, NA_real_
  )
  coordinate_registry <- data.frame(
    coordinate_id = c(first$authority$primitive_id, first$composite_ids),
    coordinate_type = c(rep("primitive", b), rep("composite", k)),
    canonical_order = seq_len(b + k),
    stringsAsFactors = FALSE
  )
  pattern_registry <- data.frame(
    pattern_id = first$pattern_ids,
    exact_pattern_key = first$pattern_keys,
    retained_taxon_count = vapply(first$patterns, function(x) {
      length(x$retained_ids)
    }, integer(1)),
    truth_plan_bytes = vapply(first$patterns, function(x) x$bytes, numeric(1)),
    stringsAsFactors = FALSE
  )
  composite_provenance <- data.frame(
    coordinate_id = first$composite_ids,
    exact_member_key = first$bstar_keys,
    member_count = lengths(first$bstar_members),
    member_text = vapply(first$bstar_members, function(ids) {
      paste(first$authority$primitive_id[ids], collapse = "|")
    }, character(1)),
    stringsAsFactors = FALSE
  )
  result <- list(
    state_matrix = state,
    numeric_matrix = numeric,
    coordinate_registry = coordinate_registry,
    pattern_registry = pattern_registry,
    gene_to_pattern = data.frame(
      gene_id = first$gene_ids,
      pattern_id = first$pattern_ids[first$gene_to_pattern],
      stringsAsFactors = FALSE
    ),
    composite_provenance = composite_provenance,
    truth_plans = first$patterns,
    internal_counts = data.frame(
      coordinate_id = first$authority$primitive_id[internal],
      mapped_count = mapped_count[internal],
      NA_topo_count = topo_count[internal],
      support = support[internal],
      stringsAsFactors = FALSE
    ),
    metrics = list(
      first_pass_seconds = first$elapsed,
      second_pass_seconds = unname(second_elapsed),
      total_seconds = first$elapsed + unname(second_elapsed),
      unique_patterns = length(first$patterns),
      unique_bstar = k,
      pattern_cache_bytes = sum(pattern_registry$truth_plan_bytes),
      bstar_peak_pending_bytes = first$bstar_accumulator$peak_pending_bytes,
      bstar_flush_count = first$bstar_accumulator$flush_count,
      rss_stage_samples = rss_samples,
      first_method = first_method,
      bstar_threshold_bytes = bstar_threshold_bytes,
      taxa_min = min(first$taxon_counts),
      taxa_median = stats::median(first$taxon_counts),
      taxa_max = max(first$taxon_counts)
    ),
    authority = first$authority
  )
  component_bytes <- vapply(result[names(result) != "metrics"], function(x) {
    as.numeric(object.size(x))
  }, numeric(1))
  largest <- names(component_bytes)[which.max(component_bytes)]
  result$metrics$top_level_component_bytes <- component_bytes
  result$metrics$largest_top_level_component <- largest
  result$metrics$largest_top_level_component_bytes <- unname(component_bytes[[largest]])
  result$metrics$compact_object_bytes <- as.numeric(object.size(result))
  class(result) <- c("arch000_compact_result", "list")
  result
}

arch_composite_value_by_primitive <- function(result) {
  n <- nrow(result$state_matrix)
  b <- result$authority$primitive_count
  output <- matrix(NA_real_, nrow = n, ncol = b, dimnames = dimnames(result$state_matrix))
  composite_col <- stats::setNames(
    seq_len(nrow(result$composite_provenance)) + b,
    result$composite_provenance$exact_member_key
  )
  for (i in seq_len(n)) {
    plan <- result$truth_plans[[match(
      result$gene_to_pattern$pattern_id[[i]], names(result$truth_plans)
    )]]
    if (!length(plan$composites)) next
    for (composite in plan$composites) {
      output[i, composite$members] <- result$numeric_matrix[
        i, composite_col[[composite$key]]
      ]
    }
  }
  output
}

arch_paired_final_tokens <- function(fixed, free) {
  if (!identical(dimnames(fixed$state_matrix), dimnames(free$state_matrix))) {
    arch_stop("Paired compact results require identical primitive axes.")
  }
  fixed_state <- matrix(as.integer(fixed$state_matrix), nrow = nrow(fixed$state_matrix))
  free_state <- matrix(as.integer(free$state_matrix), nrow = nrow(free$state_matrix))
  dimnames(fixed_state) <- dimnames(free_state) <- dimnames(fixed$state_matrix)
  b <- ncol(fixed_state)
  fixed_primitive <- fixed$numeric_matrix[, seq_len(b), drop = FALSE]
  free_primitive <- free$numeric_matrix[, seq_len(b), drop = FALSE]
  fixed_fused <- arch_composite_value_by_primitive(fixed)
  free_fused <- arch_composite_value_by_primitive(free)
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
