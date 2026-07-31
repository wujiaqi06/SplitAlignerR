## ARCH000A development-only compact retained-taxa registry.
## Requires dev/ARCH000/prototype/arch000_common.R.

a_stop <- function(...) stop(..., call. = FALSE)

a_assert <- function(value, message) {
  if (!isTRUE(value)) a_stop(message)
  invisible(TRUE)
}

a_elapsed <- function(expression) {
  started <- proc.time()[["elapsed"]]
  value <- force(expression)
  list(value = value, seconds = unname(proc.time()[["elapsed"]] - started))
}

a_raw_hex <- function(value) {
  paste(sprintf("%02x", as.integer(value)), collapse = "")
}

a_hex_raw <- function(value) {
  value <- enc2utf8(as.character(value))
  if (nchar(value, type = "bytes") %% 2L) a_stop("Hex payload has odd length.")
  starts <- seq.int(1L, nchar(value), by = 2L)
  as.raw(strtoi(substring(value, starts, starts + 1L), base = 16L))
}

a_pack_ids <- function(ids, universe_size) {
  ids <- sort(unique(as.integer(ids)), method = "radix")
  if (anyNA(ids) || any(ids < 1L) || any(ids > universe_size)) {
    a_stop("Taxon ID is outside the compact-bitset universe.")
  }
  bytes <- integer(ceiling(universe_size / 8))
  if (length(ids)) {
    byte_index <- ((ids - 1L) %/% 8L) + 1L
    bit_index <- (ids - 1L) %% 8L
    grouped <- rowsum(
      bitwShiftL(1L, bit_index), group = byte_index, reorder = FALSE
    )
    bytes[as.integer(rownames(grouped))] <- grouped[, 1L]
  }
  as.raw(bytes)
}

a_unpack_ids <- function(bits, universe_size) {
  values <- as.integer(bits)
  ids <- seq_len(universe_size)
  byte_index <- ((ids - 1L) %/% 8L) + 1L
  bit_index <- (ids - 1L) %% 8L
  ids[bitwAnd(values[byte_index], bitwShiftL(1L, bit_index)) != 0L]
}

a_pattern_exact_key <- function(bits) {
  paste0("PB1:", a_raw_hex(bits))
}

a_pattern_key_bits <- function(key) {
  if (!startsWith(key, "PB1:")) a_stop("Invalid ARCH000A pattern key.")
  a_hex_raw(substring(key, 5L))
}

a_scan_gene_patterns <- function(input, authority,
                                 method = c("taxa_scan", "full_parse")) {
  method <- match.arg(method)
  gene_ids <- character()
  keys <- character()
  bits <- list()
  taxon_counts <- integer()
  phase <- c(
    record_boundary = 0, tip_tokenization = 0, taxon_id_mapping = 0,
    pattern_key_construction = 0
  )
  count <- arch_iterate_records(input, function(record, index) {
    gene_ids[[index]] <<- record$id
    timed <- a_elapsed(if (method == "taxa_scan") {
      arch_scan_tips(record$newick)
    } else {
      arch_complete_parse_tips(record$newick)
    })
    phase[["tip_tokenization"]] <<- phase[["tip_tokenization"]] + timed$seconds
    timed <- a_elapsed(arch_taxa_to_ids(timed$value, authority))
    retained <- timed$value
    phase[["taxon_id_mapping"]] <<- phase[["taxon_id_mapping"]] + timed$seconds
    timed <- a_elapsed({
      packed <- a_pack_ids(retained, length(authority$taxa))
      list(bits = packed, key = a_pattern_exact_key(packed))
    })
    phase[["pattern_key_construction"]] <<-
      phase[["pattern_key_construction"]] + timed$seconds
    bits[[index]] <<- timed$value$bits
    keys[[index]] <<- timed$value$key
    taxon_counts[[index]] <<- length(retained)
  })
  if (!count) a_stop("Pattern scan found no gene-tree records.")
  if (anyDuplicated(gene_ids)) a_stop("Duplicate gene identifiers are invalid.")
  list(
    gene_ids = gene_ids,
    exact_pattern_keys = keys,
    exact_pattern_bits = bits,
    taxon_counts = taxon_counts,
    locus_count = count,
    phase_seconds = phase,
    method = method
  )
}

a_make_pattern_registry <- function(scans, authority) {
  if (!is.list(scans) || !length(scans)) a_stop("At least one scan is required.")
  all_keys <- unlist(lapply(scans, function(x) x$exact_pattern_keys), use.names = FALSE)
  keys <- sort(unique(all_keys), method = "radix")
  bits_by_key <- new.env(hash = TRUE, parent = emptyenv())
  for (scan in scans) {
    for (i in seq_along(scan$exact_pattern_keys)) {
      key <- scan$exact_pattern_keys[[i]]
      candidate <- scan$exact_pattern_bits[[i]]
      if (exists(key, envir = bits_by_key, inherits = FALSE)) {
        a_assert(
          identical(get(key, bits_by_key, inherits = FALSE), candidate),
          "Exact pattern-key collision did not resolve to identical bitsets."
        )
      } else {
        assign(key, candidate, envir = bits_by_key)
      }
    }
  }
  pattern_bits <- lapply(keys, get, envir = bits_by_key, inherits = FALSE)
  pattern_ids <- sprintf("P%08d", seq_along(keys))
  registry <- list(
    pattern_ids = pattern_ids,
    exact_pattern_keys = keys,
    exact_pattern_bits = pattern_bits,
    retained_taxon_count = vapply(
      pattern_bits, function(x) length(a_unpack_ids(x, length(authority$taxa))),
      integer(1)
    ),
    universe_size = length(authority$taxa),
    key_bytes = ceiling(length(authority$taxa) / 8),
    mappings = lapply(scans, function(scan) {
      index <- match(scan$exact_pattern_keys, keys)
      a_assert(!anyNA(index), "Gene-to-pattern remap failed.")
      data.frame(
        gene_id = scan$gene_ids,
        pattern_id = pattern_ids[index],
        exact_pattern_key = scan$exact_pattern_keys,
        stringsAsFactors = FALSE
      )
    })
  )
  registry$component_bytes <- c(
    exact_pattern_keys = as.numeric(object.size(registry$exact_pattern_keys)),
    exact_pattern_bits = as.numeric(object.size(registry$exact_pattern_bits)),
    pattern_ids = as.numeric(object.size(registry$pattern_ids)),
    mappings = as.numeric(object.size(registry$mappings))
  )
  registry$total_bytes <- as.numeric(object.size(registry))
  class(registry) <- c("arch000a_pattern_registry", "list")
  registry
}

a_registry_retained_ids <- function(registry, pattern_id) {
  index <- match(pattern_id, registry$pattern_ids)
  if (is.na(index)) a_stop(sprintf("Unknown pattern ID: %s", pattern_id))
  a_unpack_ids(registry$exact_pattern_bits[[index]], registry$universe_size)
}

a_exact_bucket_registry <- function(bitsets, hash_fn) {
  exact <- vapply(bitsets, a_pattern_exact_key, character(1))
  bucket <- vapply(bitsets, hash_fn, character(1))
  grouped <- split(seq_along(exact), bucket, drop = TRUE)
  resolved <- character()
  for (indices in grouped) {
    candidates <- exact[indices]
    resolved <- c(resolved, unique(candidates))
  }
  sort(unique(resolved), method = "radix")
}

a_reverse_registry_invariant <- function(scans, authority) {
  forward <- a_make_pattern_registry(scans, authority)
  reversed_scans <- lapply(scans, function(scan) {
    index <- rev(seq_len(scan$locus_count))
    scan$gene_ids <- scan$gene_ids[index]
    scan$exact_pattern_keys <- scan$exact_pattern_keys[index]
    scan$exact_pattern_bits <- scan$exact_pattern_bits[index]
    scan$taxon_counts <- scan$taxon_counts[index]
    scan
  })
  reversed <- a_make_pattern_registry(reversed_scans, authority)
  identical(forward$pattern_ids, reversed$pattern_ids) &&
    identical(forward$exact_pattern_keys, reversed$exact_pattern_keys) &&
    identical(forward$exact_pattern_bits, reversed$exact_pattern_bits)
}
