## ENGINE001 isolated packed truth-plan schema candidates.
## This file is development evidence and is not linked into the package.

source("dev/ARCH000A/prototype/load_arch000a.R")

e1_record_header_bytes <- 144L

e1_u32 <- function(values) {
  values <- as.double(values)
  if (anyNA(values) || any(values < 0) || any(values > 2^32 - 1) ||
      any(values != floor(values))) {
    stop("ENGINE001 u32 value is out of range.", call. = FALSE)
  }
  out <- raw()
  for (value in values) {
    low <- value %% 2^16
    high <- floor(value / 2^16)
    out <- c(out, writeBin(as.integer(low), raw(), size = 2L, endian = "little"),
             writeBin(as.integer(high), raw(), size = 2L, endian = "little"))
  }
  out
}

e1_read_u32 <- function(bytes, offset, count = 1L) {
  stopifnot(offset >= 1L, count >= 0L)
  if (!count) return(list(value = numeric(), next_offset = offset))
  end <- offset + count * 4L - 1L
  if (end > length(bytes)) stop("Truncated ENGINE001 u32 field.", call. = FALSE)
  con <- rawConnection(bytes[offset:end], open = "rb")
  on.exit(close(con), add = TRUE)
  low <- readBin(con, integer(), n = count * 2L, size = 2L,
                 signed = FALSE, endian = "little")
  value <- as.double(low[seq.int(1L, length(low), by = 2L)]) +
    as.double(low[seq.int(2L, length(low), by = 2L)]) * 2^16
  list(value = value, next_offset = end + 1L)
}

e1_plan_from_components <- function(retained, states, projected, authority) {
  active <- which(!is.na(projected))
  grouped <- split(active, projected[active], drop = TRUE)
  composites <- list()
  for (query in names(grouped)) {
    members <- sort(as.integer(grouped[[query]]), method = "radix")
    fused <- members[states[members] == 2L]
    if (length(fused)) {
      if (length(fused) != length(members) || length(fused) < 2L) {
        stop("Decoded plan contains an invalid fusion fiber.", call. = FALSE)
      }
      key <- arch_member_key(fused)
      composites[[key]] <- list(
        key = key, members = fused, projected_split = query
      )
    }
  }
  plan <- list(
    pattern_key = arch_pattern_key(retained),
    retained_ids = retained,
    state_template = as.integer(states),
    projected_split = projected,
    side_a_size = NULL,
    side_b_size = NULL,
    composites = composites,
    eligible = which(states == 0L),
    bytes = NA_real_
  )
  plan$bytes <- as.numeric(object.size(plan))
  plan
}

e1_fixed_prefix <- function(plan, authority) {
  c(
    a_pack_ids(plan$retained_ids, length(authority$taxa)),
    a_pack_states(plan$state_template)
  )
}

e1_decode_prefix <- function(body, authority) {
  layout <- a_truth_layout(authority)
  prefix <- layout$key_bytes + layout$state_bytes
  if (length(body) < prefix) stop("Packed plan prefix is truncated.", call. = FALSE)
  retained <- a_unpack_ids(body[seq_len(layout$key_bytes)], layout$taxa)
  states <- a_unpack_states(
    body[layout$key_bytes + seq_len(layout$state_bytes)], layout$primitive
  )
  list(retained = retained, states = states, next_offset = prefix + 1L)
}

e1_encode_dense <- function(plan, authority) {
  a_pack_truth_plan(plan, authority)
}

e1_decode_dense <- function(body, authority) {
  a_unpack_truth_plan(body, authority)
}

e1_encode_sparse <- function(plan, authority) {
  active <- which(!is.na(plan$projected_split))
  records <- lapply(active, function(index) {
    ids <- a_split_ids_from_key(plan$projected_split[[index]])
    c(e1_u32(c(index, length(ids))), e1_u32(ids))
  })
  c(e1_fixed_prefix(plan, authority), e1_u32(length(active)),
    unlist(records, use.names = FALSE))
}

e1_decode_sparse <- function(body, authority) {
  prefix <- e1_decode_prefix(body, authority)
  cursor <- prefix$next_offset
  count <- e1_read_u32(body, cursor)
  active_count <- as.integer(count$value[[1L]])
  cursor <- count$next_offset
  projected <- rep.int(NA_character_, authority$primitive_count)
  for (unused in seq_len(active_count)) {
    metadata <- e1_read_u32(body, cursor, 2L)
    primitive <- as.integer(metadata$value[[1L]])
    selected <- as.integer(metadata$value[[2L]])
    ids <- e1_read_u32(body, metadata$next_offset, selected)
    cursor <- ids$next_offset
    if (primitive < 1L || primitive > authority$primitive_count ||
        !is.na(projected[[primitive]])) {
      stop("Sparse plan has an invalid primitive index.", call. = FALSE)
    }
    projected[[primitive]] <- arch_split_key(as.integer(ids$value), prefix$retained)
  }
  if (cursor != length(body) + 1L) {
    stop("Sparse plan has trailing or malformed payload.", call. = FALSE)
  }
  e1_plan_from_components(prefix$retained, prefix$states, projected, authority)
}

e1_query_entry <- function(query, authority) {
  ids <- a_split_ids_from_key(query)
  dense <- a_pack_ids(ids, length(authority$taxa))
  sparse <- e1_u32(ids)
  use_sparse <- length(sparse) < length(dense)
  payload <- if (use_sparse) sparse else dense
  encoding <- if (use_sparse) 2L else 1L
  c(as.raw(c(encoding, 0L, 0L, 0L)),
    e1_u32(c(length(ids), length(payload))), payload)
}

e1_encode_hybrid <- function(plan, authority) {
  active <- which(!is.na(plan$projected_split))
  queries <- sort(unique(plan$projected_split[active]), method = "radix")
  references <- match(plan$projected_split[active], queries)
  entries <- lapply(queries, e1_query_entry, authority = authority)
  lengths <- vapply(entries, length, integer(1))
  offsets <- c(0, cumsum(lengths))
  c(
    e1_fixed_prefix(plan, authority),
    e1_u32(c(length(active), length(queries))),
    e1_u32(references),
    e1_u32(offsets),
    unlist(entries, use.names = FALSE)
  )
}

e1_decode_hybrid <- function(body, authority) {
  prefix <- e1_decode_prefix(body, authority)
  metadata <- e1_read_u32(body, prefix$next_offset, 2L)
  active_count <- as.integer(metadata$value[[1L]])
  query_count <- as.integer(metadata$value[[2L]])
  refs <- e1_read_u32(body, metadata$next_offset, active_count)
  offsets <- e1_read_u32(body, refs$next_offset, query_count + 1L)
  pool_start <- offsets$next_offset
  if (!identical(offsets$value[[1L]], 0) ||
      tail(offsets$value, 1L) != length(body) - pool_start + 1L) {
    stop("Hybrid query-pool offsets are invalid.", call. = FALSE)
  }
  queries <- character(query_count)
  for (i in seq_len(query_count)) {
    start <- pool_start + as.integer(offsets$value[[i]])
    end <- pool_start + as.integer(offsets$value[[i + 1L]]) - 1L
    if (end < start + 11L || end > length(body)) {
      stop("Hybrid query entry is truncated.", call. = FALSE)
    }
    encoding <- as.integer(body[[start]])
    header <- e1_read_u32(body, start + 4L, 2L)
    selected <- as.integer(header$value[[1L]])
    payload_bytes <- as.integer(header$value[[2L]])
    payload_start <- header$next_offset
    if (payload_start + payload_bytes - 1L != end) {
      stop("Hybrid query payload length differs.", call. = FALSE)
    }
    payload <- body[payload_start:end]
    ids <- if (encoding == 1L) {
      if (payload_bytes != ceiling(length(authority$taxa) / 8)) {
        stop("Dense hybrid query has the wrong width.", call. = FALSE)
      }
      a_unpack_ids(payload, length(authority$taxa))
    } else if (encoding == 2L) {
      decoded <- e1_read_u32(payload, 1L, selected)
      if (decoded$next_offset != length(payload) + 1L) {
        stop("Sparse hybrid query has trailing data.", call. = FALSE)
      }
      as.integer(decoded$value)
    } else {
      stop("Hybrid query encoding is unknown.", call. = FALSE)
    }
    if (length(ids) != selected) {
      stop("Hybrid query selected-count differs.", call. = FALSE)
    }
    queries[[i]] <- arch_split_key(ids, prefix$retained)
  }
  active <- which(prefix$states != 1L)
  if (length(active) != active_count || any(refs$value < 1) ||
      any(refs$value > query_count)) {
    stop("Hybrid active-query references are invalid.", call. = FALSE)
  }
  projected <- rep.int(NA_character_, authority$primitive_count)
  projected[active] <- queries[as.integer(refs$value)]
  e1_plan_from_components(prefix$retained, prefix$states, projected, authority)
}

e1_candidate_table <- function() {
  list(
    dense_fixed_width = list(
      encode = e1_encode_dense, decode = e1_decode_dense,
      direct_query = "YES_FIXED_OFFSET"
    ),
    eligible_sparse_records = list(
      encode = e1_encode_sparse, decode = e1_decode_sparse,
      direct_query = "NO_VARIABLE_SCAN_WITHOUT_SECONDARY_INDEX"
    ),
    hybrid_deduplicated_query_pool = list(
      encode = e1_encode_hybrid, decode = e1_decode_hybrid,
      direct_query = "YES_U32_REFERENCE_PLUS_OFFSET_TABLE"
    )
  )
}

e1_plan_shape <- function(plan) {
  active <- which(!is.na(plan$projected_split))
  queries <- unique(plan$projected_split[active])
  side_sizes <- vapply(queries, function(query) {
    length(a_split_ids_from_key(query))
  }, integer(1))
  list(active = length(active), queries = length(queries), side_sizes = side_sizes)
}

e1_project_candidate <- function(candidate, shapes, taxa, primitive,
                                 source_taxa = 302L, source_primitive = 601L) {
  key_bytes <- ceiling(taxa / 8)
  state_bytes <- ceiling(primitive / 4)
  values <- vapply(shapes, function(shape) {
    active <- max(1L, round(shape$active / source_primitive * primitive))
    if (candidate == "dense_fixed_width") {
      return(e1_record_header_bytes + key_bytes + state_bytes +
               primitive * key_bytes)
    }
    scaled_sides <- pmax(1L, round(shape$side_sizes / source_taxa * taxa))
    if (candidate == "eligible_sparse_records") {
      mean_record <- mean(8 + 4 * scaled_sides)
      return(e1_record_header_bytes + key_bytes + state_bytes + 4 +
               active * mean_record)
    }
    queries <- max(1L, round(shape$queries / source_primitive * primitive))
    mean_entry <- mean(12 + pmin(key_bytes, 4 * scaled_sides))
    e1_record_header_bytes + key_bytes + state_bytes + 8 +
      4 * active + 4 * (queries + 1) + queries * mean_entry
  }, numeric(1))
  c(min = min(values), median = median(values), mean = mean(values), max = max(values))
}

e1_run_schema_comparison <- function(species_path, fixed_path, free_path,
                                     output_csv, roundtrip_output) {
  authority <- arch_species_authority(species_path)
  fixed_scan <- a_scan_gene_patterns(fixed_path, authority)
  free_scan <- a_scan_gene_patterns(free_path, authority)
  registry <- a_make_pattern_registry(list(fixed_scan, free_scan), authority)
  build_start <- proc.time()[["elapsed"]]
  plans <- lapply(registry$pattern_ids, function(pattern_id) {
    a_plan_for_pattern(registry, authority, pattern_id)
  })
  build_seconds <- unname(proc.time()[["elapsed"]] - build_start)
  shapes <- lapply(plans, e1_plan_shape)
  rows <- list()
  roundtrip <- list()
  candidates <- e1_candidate_table()
  for (name in names(candidates)) {
    candidate <- candidates[[name]]
    started <- proc.time()[["elapsed"]]
    encoded <- lapply(plans, candidate$encode, authority = authority)
    encode_seconds <- unname(proc.time()[["elapsed"]] - started)
    started <- proc.time()[["elapsed"]]
    decoded <- lapply(encoded, candidate$decode, authority = authority)
    decode_seconds <- unname(proc.time()[["elapsed"]] - started)
    equal <- mapply(
      a_plan_scientific_equal, decoded, plans,
      MoreArgs = list(authority = authority), USE.NAMES = FALSE
    )
    sizes <- vapply(encoded, length, integer(1)) + e1_record_header_bytes
    rows[[length(rows) + 1L]] <- data.frame(
      candidate = name,
      scope = "MEASURED_AUTHORITY_302",
      taxa = length(authority$taxa),
      primitive_coordinates = authority$primitive_count,
      patterns = length(plans),
      min_record_bytes = min(sizes),
      median_record_bytes = median(sizes),
      mean_record_bytes = mean(sizes),
      max_record_bytes = max(sizes),
      total_record_bytes = sum(sizes),
      encode_seconds = encode_seconds,
      decode_seconds = decode_seconds,
      roundtrip_pass = all(equal),
      direct_query_feasibility = candidate$direct_query,
      selected = name == "hybrid_deduplicated_query_pool",
      measured_or_projected = "MEASURED",
      stringsAsFactors = FALSE
    )
    roundtrip[[name]] <- data.frame(
      candidate = name,
      plans_tested = length(equal),
      plans_equal = sum(equal),
      plans_failed = sum(!equal),
      verdict = if (all(equal)) "PASS" else "FAIL",
      stringsAsFactors = FALSE
    )
    for (taxa in c(1000L, 5000L)) {
      primitive <- 2L * taxa - 3L
      projected <- e1_project_candidate(name, shapes, taxa, primitive)
      rows[[length(rows) + 1L]] <- data.frame(
        candidate = name,
        scope = sprintf("PROJECTED_%d_TAXA_OBSERVED_302_SHAPE", taxa),
        taxa = taxa,
        primitive_coordinates = primitive,
        patterns = length(plans),
        min_record_bytes = projected[["min"]],
        median_record_bytes = projected[["median"]],
        mean_record_bytes = projected[["mean"]],
        max_record_bytes = projected[["max"]],
        total_record_bytes = projected[["mean"]] * length(plans),
        encode_seconds = NA_real_,
        decode_seconds = NA_real_,
        roundtrip_pass = NA,
        direct_query_feasibility = candidate$direct_query,
        selected = name == "hybrid_deduplicated_query_pool",
        measured_or_projected = "PROJECTED_NOT_EXECUTED",
        stringsAsFactors = FALSE
      )
    }
  }
  result <- do.call(rbind, rows)
  result$truth_plan_build_seconds <- build_seconds
  result$authority_pattern_count <- length(registry$pattern_ids)
  result$authority_unique_fraction <- length(registry$pattern_ids) /
    fixed_scan$locus_count
  write.csv(result, output_csv, row.names = FALSE, quote = TRUE)
  write.table(do.call(rbind, roundtrip), roundtrip_output,
              row.names = FALSE, quote = FALSE, sep = "\t")
  invisible(result)
}

if (sys.nframe() == 0L) {
  args <- commandArgs(trailingOnly = TRUE)
  if (length(args) != 5L) {
    stop("Usage: packed_schema_comparison.R species fixed free output.csv roundtrip.txt",
         call. = FALSE)
  }
  e1_run_schema_comparison(args[[1L]], args[[2L]], args[[3L]],
                           args[[4L]], args[[5L]])
}
