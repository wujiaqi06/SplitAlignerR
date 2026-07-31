## Deterministic engineering stress inputs with 302-taxon-like missingness.
## These are not biological datasets.

a_generate_unique_pattern_bits <- function(unique_count, universe_size = 302L,
                                           seed = 20260731L,
                                           missing_range = 0:19) {
  unique_count <- as.integer(unique_count)
  a_assert(unique_count >= 1L, "Stress generator requires a positive count.")
  set.seed(seed)
  seen <- new.env(hash = TRUE, parent = emptyenv())
  output <- vector("list", unique_count)
  count <- 0L
  attempts <- 0L
  max_attempts <- max(100000L, unique_count * 200L)
  while (count < unique_count && attempts < max_attempts) {
    attempts <- attempts + 1L
    missing <- sample(missing_range, 1L)
    deleted <- if (missing) sample.int(universe_size, missing) else integer()
    retained <- setdiff(seq_len(universe_size), deleted)
    bits <- a_pack_ids(retained, universe_size)
    key <- a_pattern_exact_key(bits)
    if (!exists(key, seen, inherits = FALSE)) {
      count <- count + 1L
      output[[count]] <- bits
      assign(key, TRUE, seen)
    }
  }
  if (count != unique_count) {
    a_stop(sprintf(
      "Stress generator produced %d/%d unique patterns after %d attempts.",
      count, unique_count, attempts
    ))
  }
  keys <- vapply(output, a_pattern_exact_key, character(1))
  order <- order(keys, method = "radix")
  list(
    bits = output[order],
    keys = keys[order],
    universe_size = universe_size,
    seed = seed,
    missing_range = range(missing_range),
    engineering_stress_only = TRUE
  )
}

a_stress_pattern_sequence <- function(locus_count, unique_fraction,
                                      ordering = c(
                                        "original", "grouped", "interleaved",
                                        "reversed", "random"
                                      ),
                                      seed = 20260731L) {
  ordering <- match.arg(ordering)
  locus_count <- as.integer(locus_count)
  unique_count <- max(1L, min(locus_count, as.integer(round(
    locus_count * unique_fraction
  ))))
  base <- rep(seq_len(unique_count), length.out = locus_count)
  if (ordering == "grouped") {
    base <- sort(base, method = "radix")
  } else if (ordering == "interleaved") {
    base <- rep(seq_len(unique_count), length.out = locus_count)
  } else if (ordering == "reversed") {
    base <- rev(base)
  } else if (ordering == "random") {
    set.seed(seed)
    base <- sample(base, length(base), replace = FALSE)
  } else {
    stride <- if (unique_count > 1L) unique_count - 1L else 1L
    base <- ((seq_len(locus_count) - 1L) * stride) %% unique_count + 1L
  }
  list(
    pattern_index = as.integer(base),
    locus_count = locus_count,
    unique_count = unique_count,
    unique_fraction = unique_count / locus_count,
    ordering = ordering,
    seed = seed
  )
}

a_stress_registry <- function(patterns, locus_count = length(patterns$bits)) {
  pattern_ids <- sprintf("P%08d", seq_along(patterns$bits))
  registry <- list(
    pattern_ids = pattern_ids,
    exact_pattern_keys = patterns$keys,
    exact_pattern_bits = patterns$bits,
    retained_taxon_count = vapply(
      patterns$bits,
      function(x) length(a_unpack_ids(x, patterns$universe_size)),
      integer(1)
    ),
    universe_size = patterns$universe_size,
    key_bytes = ceiling(patterns$universe_size / 8),
    mappings = list()
  )
  registry$component_bytes <- c(
    exact_pattern_keys = as.numeric(object.size(registry$exact_pattern_keys)),
    exact_pattern_bits = as.numeric(object.size(registry$exact_pattern_bits)),
    pattern_ids = as.numeric(object.size(registry$pattern_ids))
  )
  registry$total_bytes <- as.numeric(object.size(registry))
  class(registry) <- c("arch000a_pattern_registry", "list")
  registry
}

a_synthetic_body_provider <- function(template_body) {
  force(template_body)
  function(index, registry, authority, layout) {
    body <- template_body
    body[seq_len(layout$key_bytes)] <- registry$exact_pattern_bits[[index]]
    body
  }
}
