gene_records_from_lines <- function(lines) {
  lines <- enc2utf8(trimws(lines))
  lines <- lines[nzchar(lines) & !startsWith(lines, "#")]
  if (!length(lines)) {
    stop("The gene-tree file contains no Newick records.", call. = FALSE)
  }

  embedded_ids <- rep(NA_character_, length(lines))
  newicks <- character(length(lines))
  for (i in seq_along(lines)) {
    record <- lines[[i]]
    first <- substr(record, 1L, 1L)
    if (first %in% c("(", "[")) {
      newicks[[i]] <- record
      next
    }

    open <- regexpr("(", record, fixed = TRUE)[[1L]]
    if (open < 2L) {
      stop(
        sprintf("Gene-tree record %d is not Newick and has no valid ID prefix.", i),
        call. = FALSE
      )
    }
    prefix <- trimws(substr(record, 1L, open - 1L))
    if (!grepl("^[A-Za-z0-9_.-]+$", prefix)) {
      stop(
        sprintf(
          "Gene-tree record %d has an invalid ID prefix `%s`; use letters, digits, dot, underscore, or hyphen.",
          i, prefix
        ),
        call. = FALSE
      )
    }
    embedded_ids[[i]] <- prefix
    newicks[[i]] <- substr(record, open, nchar(record))
  }
  list(newicks = newicks, ids = embedded_ids)
}

unicode_whitespace_codepoint <- function(codepoint) {
  codepoint %in% c(
    0x0009:0x000D, 0x0020, 0x0085, 0x00A0, 0x1680,
    0x2000:0x200A, 0x2028, 0x2029, 0x202F, 0x205F, 0x3000
  )
}

validate_explicit_gene_ids <- function(ids, count) {
  if (!is.character(ids) || length(ids) != count) {
    stop("`gene_ids` must be a character vector with one ID per tree.",
         call. = FALSE)
  }
  if (anyNA(ids)) {
    stop("User-supplied `gene_ids` must not contain missing values.",
         call. = FALSE)
  }
  if (any(!nzchar(ids))) {
    stop("User-supplied `gene_ids` must not contain empty strings.",
         call. = FALSE)
  }

  codepoints <- lapply(enc2utf8(ids), utf8ToInt)
  has_boundary_whitespace <- vapply(codepoints, function(x) {
    unicode_whitespace_codepoint(x[[1L]]) ||
      unicode_whitespace_codepoint(x[[length(x)]])
  }, logical(1))
  if (any(has_boundary_whitespace)) {
    stop(
      "User-supplied `gene_ids` must not have leading or trailing whitespace.",
      call. = FALSE
    )
  }

  has_control <- vapply(codepoints, function(x) {
    any(x <= 0x001F | (x >= 0x007F & x <= 0x009F))
  }, logical(1))
  if (any(has_control)) {
    stop("User-supplied `gene_ids` must not contain control characters.",
         call. = FALSE)
  }
  if (anyDuplicated(ids)) {
    duplicate <- ids[duplicated(ids)][[1L]]
    stop(sprintf("Duplicate gene identifier `%s`.", duplicate), call. = FALSE)
  }
  ids
}

gene_id_byte_key <- function(ids) {
  vapply(ids, function(id) {
    paste(as.character(charToRaw(id)), collapse = "")
  }, character(1), USE.NAMES = FALSE)
}

restore_gene_id_encodings <- function(result, ids) {
  ids <- enc2utf8(ids)
  key_to_id <- stats::setNames(ids, gene_id_byte_key(ids))
  restore <- function(values) {
    restored <- unname(key_to_id[gene_id_byte_key(values)])
    if (anyNA(restored)) {
      stop(
        "Internal error: the production result returned an unknown gene ID.",
        call. = FALSE
      )
    }
    restored
  }

  rownames(result$state_matrix) <- ids
  rownames(result$numeric_matrix) <- ids
  for (component in c(
    "state_ledger", "composite_ledger", "gene_provenance", "diagnostics"
  )) {
    if ("gene_id" %in% names(result[[component]])) {
      result[[component]]$gene_id <- restore(result[[component]]$gene_id)
    }
  }
  result
}

complete_gene_ids <- function(ids, count, user_supplied = FALSE) {
  if (user_supplied) {
    return(validate_explicit_gene_ids(ids, count))
  }
  if (is.null(ids)) {
    ids <- rep(NA_character_, count)
  }
  if (!is.character(ids) || length(ids) != count) {
    stop("`gene_ids` must be a character vector with one ID per tree.",
         call. = FALSE)
  }
  ids <- trimws(ids)
  used <- ids[!is.na(ids) & nzchar(ids)]
  for (i in which(is.na(ids) | !nzchar(ids))) {
    candidate_number <- i
    repeat {
      candidate <- sprintf("gene_%06d", candidate_number)
      if (!candidate %in% used) {
        break
      }
      candidate_number <- candidate_number + count
    }
    ids[[i]] <- candidate
    used <- c(used, candidate)
  }
  if (anyDuplicated(ids)) {
    duplicate <- ids[duplicated(ids)][[1L]]
    stop(sprintf("Duplicate gene identifier `%s`.", duplicate), call. = FALSE)
  }
  ids
}

as_gene_newicks <- function(gene_trees, gene_ids = NULL) {
  source <- "R object"
  inferred_ids <- NULL

  if (inherits(gene_trees, "multiPhylo")) {
    newicks <- enc2utf8(ape::write.tree(gene_trees))
    inferred_ids <- names(gene_trees)
    source <- "ape::multiPhylo"
  } else if (inherits(gene_trees, "phylo")) {
    newicks <- enc2utf8(ape::write.tree(gene_trees))
    inferred_ids <- NULL
    source <- "ape::phylo"
  } else if (is.list(gene_trees)) {
    if (!length(gene_trees) ||
        !all(vapply(gene_trees, inherits, logical(1), what = "phylo"))) {
      stop("A gene-tree list must contain only `ape::phylo` objects.",
           call. = FALSE)
    }
    newicks <- enc2utf8(vapply(
      gene_trees, ape::write.tree, character(1)
    ))
    inferred_ids <- names(gene_trees)
    source <- "list of ape::phylo"
  } else if (is.character(gene_trees)) {
    if (length(gene_trees) == 1L && !is.na(gene_trees) &&
        file.exists(gene_trees)) {
      source <- normalizePath(gene_trees, winslash = "/", mustWork = TRUE)
      records <- gene_records_from_lines(readLines(
        gene_trees, warn = FALSE, encoding = "UTF-8"
      ))
      newicks <- records$newicks
      inferred_ids <- records$ids
    } else {
      newicks <- enc2utf8(gene_trees)
      inferred_ids <- names(gene_trees)
      source <- if (length(gene_trees) == 1L) {
        "Newick string"
      } else {
        "Newick character vector"
      }
    }
  } else {
    stop(
      paste0(
        "`gene_trees` must be Newick text/file input, one `ape::phylo`, ",
        "an `ape::multiPhylo`, or a list of `phylo` objects."
      ),
      call. = FALSE
    )
  }

  if (!length(newicks) || anyNA(newicks) || any(!nzchar(trimws(newicks)))) {
    stop("Every gene tree must contain a nonempty Newick string.", call. = FALSE)
  }
  ids <- complete_gene_ids(
    if (is.null(gene_ids)) inferred_ids else gene_ids,
    length(newicks),
    user_supplied = !is.null(gene_ids)
  )
  list(newicks = unname(newicks), ids = ids, source = source)
}

#' Align gene trees to the species-tree branch-coordinate system
#'
#' Restrict the reference tree to each gene's retained taxa, classify every
#' primitive coordinate by graph-first semantics, and then query the empirical
#' gene-tree splits. Structural state is kept separate from finite numeric
#' evidence: a recovered split with a software failure marker remains `mapped`
#' while its numeric value is unavailable.
#'
#' @param species_tree Reference species tree: one `ape::phylo`, a Newick
#'   string, or a file path. Reference lengths, internal labels/support, and
#'   annotation blocks are ignored with diagnostics.
#' @param gene_trees One or more empirical gene trees supplied as Newick text,
#'   a SplitAligner line-based file, one `ape::phylo`, an `ape::multiPhylo`, or
#'   a list of `phylo` objects. A line-based record may be `gene_id(tree);` or a
#'   plain Newick tree.
#' @param mode Character; `"free"` for free-topology trees or `"fixed"` for
#'   topology-constrained trees. Both modes use the same state semantics;
#'   fixed-mode topology mismatches are additionally diagnosed.
#' @param gene_ids Optional character vector overriding inferred/file IDs.
#'   Explicit IDs must be non-missing, nonempty, unique, free of control
#'   characters, and have no leading or trailing whitespace. Unicode IDs are
#'   supported.
#' @param ... Reserved; additional arguments currently signal an error.
#' @return A `splitaligner_result` list containing the primitive `state_matrix`,
#'   primitive-plus-composite `numeric_matrix`, long state and composite
#'   ledgers, coordinate provenance, structured diagnostics, validated species
#'   tree, and versioned metadata.
#' @details The single-tree state alphabet is exactly `mapped`, `NA_struct`,
#'   `NA_fuse`, and `NA_topo`. Legacy paired-workflow `residual_NA` is not a
#'   fifth state. Failure markers are never converted to zero.
#' @seealso [validate_species_tree()], [validate_branch_length_tokens()]
#' @examples
#' species <- "((A:1,B:1):1,(C:1,D:1):1);"
#' genes <- c(g1 = "((A:1,B:1):1,(C:1,D:1):1);")
#' aligned <- align_branches(species, genes)
#' aligned$state_matrix
#' @export
align_branches <- function(species_tree, gene_trees,
                           mode = c("free", "fixed"), gene_ids = NULL, ...) {
  mode <- match.arg(mode)
  dots <- list(...)
  if (length(dots)) {
    stop("Additional arguments are reserved and are not accepted yet.",
         call. = FALSE)
  }

  species <- as_species_newick(species_tree)
  genes <- as_gene_newicks(gene_trees, gene_ids = gene_ids)
  result <- cpp_align_branches(
    species$text, genes$newicks, genes$ids, mode
  )
  result <- restore_gene_id_encodings(result, genes$ids)
  result$coordinate_table <- build_coordinate_table(result)
  result$input <- list(
    species_source = species$source,
    gene_source = genes$source,
    gene_ids = genes$ids
  )
  class(result) <- c("splitaligner_result", "list")
  result
}
