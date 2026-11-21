.fusion_definitions <- function(result) {
  d <- result$composite_coordinates
  stats::setNames(as.list(d$primitive_members), d$coordinate_id)
}

.fusion_prepare <- function(result, definitions) {
  genes <- result$gene_ids
  primitive <- result$primitive_ids
  if (is.null(genes)) genes <- rownames(result$state_matrix)
  if (is.null(primitive)) primitive <- colnames(result$state_matrix)
  targets <- lapply(definitions, match, table = primitive)
  if (any(lengths(targets) < 2L) || anyNA(unlist(targets, use.names = FALSE)))
    stop("Unrecognized fusion target member.")
  p <- result$state_ledger
  g <- result$composite_ledger
  # The compact owner index points into two canonical ledgers. A deleted
  # primitive has no owner. All members of a current fusion share one owner.
  owners <- seq_len(nrow(p))
  owners[p$state == "NA_struct"] <- 0L
  f <- which(p$state == "NA_fuse")
  if (length(f)) {
    current <- match(paste(p$gene_id[f], p$composite_id[f], sep = "\r"),
                     paste(g$gene_id, g$composite_id, sep = "\r"))
    if (anyNA(current)) stop("Missing current fusion record.")
    owners[f] <- nrow(p) + current
  }
  local <- result$composite_coordinates
  sizes <- c(rep.int(1L, nrow(p)),
             lengths(local$primitive_members)[match(g$composite_id, local$coordinate_id)])
  if (anyNA(sizes)) stop("Missing current fusion definition.")
  displayed <- c(p$state == "mapped", g$recovery_status != "unrecovered")
  values <- c(p$numeric_value, g$numeric_value)
  list(genes = genes, primitive = primitive, targets = targets,
       owners = owners, sizes = sizes, displayed = displayed, values = values,
       ids = as.character(names(definitions)))
}

# Stream one numeric row from a prepared shard. Reindex only this gene's
# complete components so the native scratch space is bounded by its branches,
# rather than initialized for every gene in the shard on each call.
.fusion_numeric_row <- function(prepared, row, fusion_view) {
  primitive_count <- length(prepared$primitive)
  owners <- prepared$owners[(row - 1L) * primitive_count + seq_len(primitive_count)]
  components <- unique(owners[owners != 0L])
  owners <- match(owners, components, nomatch = 0L)
  out <- cpp_fusion_cells(owners, prepared$sizes[components], prepared$displayed[components],
                          prepared$values[components], primitive_count, 1L,
                          prepared$targets, fusion_view == "whole", FALSE)$values
  dimnames(out) <- list(prepared$genes[row], prepared$ids)
  out
}

# A disk export can reuse this compact index for one row at a time. Preparing
# it does not materialize any gene-by-fusion values or cell provenance.
.fusion_assemble <- function(result, definitions, fusion_view, gene_ids = NULL,
                             details = FALSE, prepared = NULL) {
  if (!fusion_view %in% c("whole", "direct")) stop("Unknown fusion view.")
  if (is.null(prepared)) prepared <- .fusion_prepare(result, definitions)
  if (is.null(gene_ids)) gene_ids <- prepared$genes
  rows <- match(gene_ids, prepared$genes)
  if (anyNA(rows)) stop("Unknown gene ID in fusion matrix request.")
  primitive <- prepared$primitive
  targets <- prepared$targets
  displayed <- prepared$displayed
  values <- prepared$values
  out <- cpp_fusion_cells(prepared$owners, prepared$sizes, displayed, values,
                          length(primitive), rows, targets, fusion_view == "whole", details)
  ids <- prepared$ids
  dimnames(out$values) <- list(gene_ids, ids)
  if (!details) return(out$values)

  p <- result$state_ledger
  g <- result$composite_ledger
  ref <- c("active", "decomposable", "unavailable")[out$structure]
  rec <- c("recovered", "not_recovered", "not_applicable")[out$recovery]
  status <- c("available", rep("not_applicable", 3L), "not_recovered",
              "missing_length", "nonfinite_sum", "direct_only")[out$status]
  reference_reason <- c("representable", "deleted_member", "partial_component",
                        "deleted_member_and_partial_component")[pmin(out$status, 4L)]
  reference_reason[ref != "unavailable"] <- "representable"
  construction <- rep("none", length(ref))
  construction[ref == "active"] <- "single_edge_lookup"
  construction[ref == "decomposable"] <- "selected_component_edge_sum"
  cell <- data.frame(
    gene_id = rep(gene_ids, times = length(targets)),
    composite_id = rep(ids, each = length(rows)),
    reference_state = ref, reference_reason = reference_reason, recovery_status = rec,
    numeric_status = status, numeric_available = status == "available",
    numeric_value = as.numeric(out$values), construction_mode = construction,
    stringsAsFactors = FALSE
  )
  # Store input edges once per actual component in the result and materialize
  # component records only for the requested cells. Alias indices refer to
  # incoming edges at zero-based postorder node indices in the input Newick.
  source <- c(p$source_nodes, g$source_nodes)
  numeric_status <- c(p$numeric_status, g$numeric_status)
  coordinates <- c(p$coordinate_id, g$composite_id)
  members <- c(stats::setNames(as.list(primitive), primitive), .fusion_definitions(result))
  cell$components <- I(lapply(out$sources, function(ix) {
    # Select before rendering lazy split text. Concatenating both full ledger
    # columns would expand every gene's split even for a one-cell request.
    projection <- rep(NA_character_, length(ix))
    original <- ix <= nrow(p)
    projection[original] <- p$projected_split[ix[original]]
    projection[!original] <- g$projected_split[ix[!original] - nrow(p)]
    component <- data.frame(
      coordinate_id = coordinates[ix], projected_split = projection,
      source_nodes = source[ix],
      recovery_status = ifelse(displayed[ix], "recovered", "not_recovered"),
      numeric_value = values[ix], numeric_status = numeric_status[ix],
      stringsAsFactors = FALSE
    )
    component$primitive_members <- I(unname(members[coordinates[ix]]))
    component
  }))
  cell
}

#' Inspect the source of shared fusion-column values
#'
#' @param result A result from [align_branches()].
#' @param gene_ids Optional gene IDs in the desired order.
#' @param coordinate_ids Optional shared fusion coordinate IDs.
#' @return One row per selected gene and fusion coordinate with its structural
#'   and recovery states, value, numeric status, applicable construction mode and a
#'   `components` list-column. Each component records its whole primitive
#'   member set, projected split, recovery and numeric evidence. `source_nodes`
#'   lists comma-separated, zero-based postorder node indices in the input gene
#'   Newick. Each names the incoming edge at that node. Multiple indices for
#'   one split identify degree-two aliases collapsed into one measurement.
#'   For an unavailable target, the table shows any surviving touched components,
#'   including whole components crossing the target boundary. For historical
#'   direct-only objects, rerun the alignment to record source indices.
#' @examples
#' r <- align_branches("((A,B),(C,D));", c(g1 = "(A:1,B:2);",
#'                                        g2 = "((A:1,B:2):3,(C:4,D:5):6);"))
#' fusion_cells(r, "g2")
#' @export
fusion_cells <- function(result, gene_ids = NULL, coordinate_ids = NULL) {
  if (!inherits(result, "splitaligner_result")) stop("Supply an alignment result.")
  view <- result$metadata$fusion_view
  if (is.null(view) || !identical(result$metadata$fusion_schema, "whole-component-v1"))
    stop("Rerun this alignment to record whole-component provenance.")
  # Positional ownership must use the validated gene-by-primitive ledger.
  # Validate only requested numeric cells below instead of assembling every
  # fusion value merely to inspect a small selection.
  validate_splitaligner_result_object(result, check_fusion_matrix = FALSE)
  validated_free_composites(result)
  defs <- .fusion_definitions(result)
  if (!is.null(coordinate_ids)) {
    if (!is.character(coordinate_ids) || anyNA(match(coordinate_ids, names(defs))))
      stop("Unknown fusion coordinate ID.")
    defs <- defs[coordinate_ids]
  }
  cells <- .fusion_assemble(result, defs, view, gene_ids, details = TRUE)
  index <- cbind(match(cells$gene_id, rownames(result$numeric_matrix)),
                 match(cells$composite_id, colnames(result$numeric_matrix)))
  if (!numeric_vectors_equal(cells$numeric_value, result$numeric_matrix[index])) {
    result_invariant_error("fusion source evidence disagrees with the selected numeric cells.")
  }
  cells
}
