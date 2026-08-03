engine002_raw_lex_less <- function(left, right) {
  stopifnot(is.raw(left), is.raw(right), length(left) == length(right))
  at <- which(as.integer(left) != as.integer(right))
  if (!length(at)) return(FALSE)
  as.integer(left[[at[[1L]]]]) < as.integer(right[[at[[1L]]]])
}

engine002_pack_ids <- function(ids, universe_size) {
  ids <- sort(unique(as.integer(ids)), method = "radix")
  if (anyNA(ids) || any(ids < 1L) || any(ids > universe_size)) {
    stop("taxon ID outside ENGINE002 authority universe", call. = FALSE)
  }
  bytes <- integer(ceiling(universe_size / 8))
  if (length(ids)) {
    for (id in ids) {
      byte <- ((id - 1L) %/% 8L) + 1L
      bit <- (id - 1L) %% 8L
      bytes[[byte]] <- bitwOr(bytes[[byte]], bitwShiftL(1L, bit))
    }
  }
  as.raw(bytes)
}

engine002_selected_side <- function(left, right, universe_size) {
  left <- sort(unique(as.integer(left)), method = "radix")
  right <- sort(unique(as.integer(right)), method = "radix")
  if (!length(left) || !length(right)) {
    stop("canonical query requires two nonempty sides", call. = FALSE)
  }
  left_bits <- engine002_pack_ids(left, universe_size)
  right_bits <- engine002_pack_ids(right, universe_size)
  if (length(left) < length(right)) return(left_bits)
  if (length(right) < length(left)) return(right_bits)
  if (engine002_raw_lex_less(right_bits, left_bits)) right_bits else left_bits
}

engine002_make_authority <- function(reference_authority) {
  universe <- length(reference_authority$taxa)
  terminal <- rep.int(NA_integer_, reference_authority$primitive_count)
  splits <- vector("list", reference_authority$primitive_count)
  for (i in seq_len(reference_authority$primitive_count)) {
    left <- reference_authority$side_a[[i]]
    right <- reference_authority$side_b[[i]]
    splits[[i]] <- engine002_selected_side(left, right, universe)
    if (identical(reference_authority$branch_type[[i]], "terminal")) {
      singleton <- if (length(left) == 1L) left else right
      if (length(singleton) != 1L) {
        stop("reference terminal coordinate lacks singleton side", call. = FALSE)
      }
      terminal[[i]] <- singleton[[1L]] - 1L
    }
  }
  SplitAlignerR:::.engine002_authority(
    reference_authority$taxa, terminal, splits
  )
}

engine002_plan_queries <- function(reference_authority, retained_ids, states) {
  universe <- length(reference_authority$taxa)
  queries <- vector("list", reference_authority$primitive_count)
  for (i in seq_len(reference_authority$primitive_count)) {
    if (states[[i]] == 1L) next
    left <- intersect(reference_authority$side_a[[i]], retained_ids)
    right <- intersect(reference_authority$side_b[[i]], retained_ids)
    queries[[i]] <- engine002_selected_side(left, right, universe)
  }
  queries
}

engine002_member_keys <- function(fibers, one_based = FALSE) {
  if (!length(fibers)) return(character())
  keys <- vapply(fibers, function(members) {
    members <- as.integer(members) + if (one_based) 0L else 1L
    paste(sprintf("%08x", sort(members, method = "radix")), collapse = ".")
  }, character(1))
  unname(sort(keys, method = "radix"))
}

engine002_plan_equal_reference <- function(decoded, reference, queries) {
  reference_fibers <- lapply(reference$composites, `[[`, "members")
  checks <- c(
    retained = identical(decoded$retained, engine002_pack_ids(
      reference$retained_ids, length(decoded$retained) * 8L
    )),
    states = identical(decoded$states, as.integer(reference$state_template)),
    eligible = identical(decoded$eligible_primitives,
                         as.integer(reference$eligible - 1L)),
    queries = identical(decoded$primitive_queries, queries),
    fibers = identical(engine002_member_keys(decoded$fibers),
                       engine002_member_keys(reference_fibers,
                                             one_based = TRUE))
  )
  structure(all(checks), checks = checks)
}
