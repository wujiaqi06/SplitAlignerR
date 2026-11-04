# Versioned INTEROP001 exchange layer. Core alignment and legacy RDS are unchanged.
.sx_version <- "0.2.0-development"
.sx_profile <- "single-fixed-primitive-branch-length-v1"
.sx_hash_schema <- "SAR-C14N-1-SHA256"
.sx_native_scheme <- list(id = "splitalignerr.terminal-first", version = "1")
.sx_old_scheme <- list(id = "splitaligner.branch-order.legacy", version = "1")
.sx_components <- c("schema", "producer", "contract", "axes", "identity", "tree",
                    "coordinates", "labels", "data", "preserved", "annotation")
.sx_need <- function(ok, message) {
  if (!isTRUE(ok)) stop(paste0("Exchange invariant: ", message), call. = FALSE)
}
.sx_fields <- function(x, fields, label) {
  .sx_need(is.list(x) && !is.null(names(x)) && !anyDuplicated(names(x)) &&
             setequal(names(x), fields), paste(label, "has unknown or missing fields"))
}
.sx_string <- function(x) is.character(x) && length(x) == 1L && !is.na(x) && nzchar(x)
.sx_raw_hash <- function(x) digest::digest(x, algo = "sha256", serialize = FALSE)
.sx_keys <- function(x) is.character(x) && length(x) > 0L && !anyNA(x) &&
  all(nzchar(x)) && !anyDuplicated(x)
.sx_scheme <- function(x) {
  .sx_fields(x, c("id", "version"), "label scheme")
  .sx_need(identical(x, .sx_native_scheme) || identical(x, .sx_old_scheme),
           "unknown label scheme/version; B aliases cannot identify a scheme")
  invisible(x)
}

#' Registered branch alias scopes for the exchange profile
#' @return A versioned registry. Historical registration does not certify a crosswalk.
#' @export
splitaligner_label_registry <- function() {
  list(registry_version = .sx_version,
       native = list(scheme = .sx_native_scheme,
                     scope = "R native leaf traversal, then non-root internal postorder; lowest B wins duplicate splits",
                     key_schema = "SplitAligner-canonical-split-key-v2"),
       historical = list(scheme = .sx_old_scheme,
                         authority_status = "INCOMPLETE_INDEPENDENT_ORIGINAL_AUTHORITY",
                         real_historical_migration_supported = FALSE,
                         source_bound_profile = "marine302-user-bound-20260908-v1; inspect its separate source-bound audit record",
                         note = "User supplied original old-to-APE and old-to-new files plus named reference trees; audit is scoped to those bytes, never whole-generation-history certification"))
}

.sx_geometry <- function(tree) {
  .sx_need(inherits(tree, "phylo") && !inherits(tree, "multiPhylo"),
           "species_tree must be one explicitly supplied phylo")
  tips <- .sx_utf8(tree$tip.label)
  .sx_need(.sx_keys(tips) && length(tips) >= 3L, "tree tip labels must be unique; profile needs at least three tips")
  edge <- tree$edge
  .sx_need(is.matrix(edge) && is.numeric(edge) && ncol(edge) == 2L &&
             nrow(edge) > 0L && !anyNA(edge) && all(is.finite(edge)) &&
             all(edge > 0L & edge == as.integer(edge)), "invalid phylo edge matrix")
  .sx_need(is.numeric(tree$Nnode) && length(tree$Nnode) == 1L &&
             !is.na(tree$Nnode) && tree$Nnode >= 1L && tree$Nnode == as.integer(tree$Nnode),
           "invalid phylo Nnode")
  nodes <- seq_len(length(tips) + tree$Nnode)
  .sx_need(setequal(as.vector(edge), nodes) && !anyDuplicated(edge[, 2L]),
           "tree node/edge mapping is not unique or exhaustive")
  root <- setdiff(edge[, 1L], edge[, 2L])
  .sx_need(length(root) == 1L && root > length(tips), "root must be unique and have no incoming ordinary edge")
  .sx_need(!any(edge[, 1L] <= length(tips)) &&
             setequal(setdiff(nodes, edge[, 1L]), seq_along(tips)), "tips/internal nodes do not agree with edges")
  memo <- vector("list", length(nodes)); visiting <- logical(length(nodes))
  descend <- function(node) {
    .sx_need(!visiting[[node]], "tree contains a cycle")
    if (!is.null(memo[[node]])) return(memo[[node]])
    visiting[[node]] <<- TRUE
    out <- if (node <= length(tips)) tips[[node]] else
      unlist(lapply(edge[edge[, 1L] == node, 2L], descend), use.names = FALSE)
    visiting[[node]] <<- FALSE
    .sx_need(length(out) > 0L && !anyDuplicated(out), "tree has an empty or repeated descendant taxon")
    memo[[node]] <<- sort(out, method = "radix")
    memo[[node]]
  }
  .sx_need(setequal(descend(root), tips), "tree is disconnected")
  sides <- lapply(edge[, 2L], descend)
  if (!is.null(tree$edge.length)) {
    .sx_need(is.numeric(tree$edge.length) && length(tree$edge.length) == nrow(edge) &&
               !any(is.nan(tree$edge.length) | is.infinite(tree$edge.length)), "invalid tree geometry edge lengths")
  }
  if (!is.null(tree$root.edge)) .sx_need(is.numeric(tree$root.edge) && length(tree$root.edge) == 1L &&
                                        !any(is.nan(tree$root.edge) | is.infinite(tree$root.edge)), "invalid root.edge geometry")
  list(tips = tips, root = as.integer(root), sides = sides,
       edge_length = if (is.null(tree$edge.length)) rep(NA_real_, nrow(edge)) else tree$edge.length)
}

.sx_tree_map <- function(tree, coordinates, label_ledger) {
  geometry <- .sx_geometry(tree)
  domain <- sort(geometry$tips, method = "radix")
  for (i in seq_len(nrow(coordinates))) {
    a <- coordinates$side_A_taxa[[i]]; b <- coordinates$side_B_taxa[[i]]
    .sx_need(.sx_keys(a) && .sx_keys(b) && !length(intersect(a, b)) &&
               setequal(c(a, b), domain), "coordinate split sides do not partition the exact tree taxon domain")
  }
  matches <- lapply(geometry$sides, function(side) {
    which(vapply(seq_len(nrow(coordinates)), function(i)
      setequal(side, coordinates$side_A_taxa[[i]]) || setequal(side, coordinates$side_B_taxa[[i]]), logical(1)))
  })
  .sx_need(all(lengths(matches) == 1L), "tree and coordinate ledger disagree or have non-unique split mapping")
  index <- as.integer(unlist(matches))
  .sx_need(length(index) == nrow(coordinates) && !anyDuplicated(index) &&
             setequal(index, seq_len(nrow(coordinates))),
           "root/edge ambiguity: primitive coordinates and tree edges must be a unique exhaustive bijection; no reroot/prune/merge")
  tree_id <- paste0("tree-instance2:", .sx_hash(tree))
  alias <- label_ledger$alias[match(coordinates$coordinate_id[index], label_ledger$coordinate_id)]
  out <- data.frame(tree_instance_id = tree_id,
                    coordinate_id = coordinates$coordinate_id[index],
                    canonical_split_key = coordinates$canonical_split_key[index],
                    source_alias = coordinates$source_alias[index], display_alias = alias,
                    edge_row = seq_len(nrow(tree$edge)), parent_node = as.integer(tree$edge[, 1L]),
                    child_node = as.integer(tree$edge[, 2L]), node = as.integer(tree$edge[, 2L]),
                    branch_type = coordinates$branch_type[index],
                    terminal_taxon = coordinates$terminal_taxon[index],
                    tree_branch_length = geometry$edge_length,
                    stringsAsFactors = FALSE, check.names = FALSE)
  .sx_need(all((out$branch_type == "terminal") == (out$child_node <= length(geometry$tips))),
           "terminal/internal coordinate does not match the specified tree edge")
  list(tree_instance_id = tree_id, root_node = geometry$root,
       root_has_ordinary_incoming_edge = FALSE, root_edge = tree$root.edge, edges = out)
}

.sx_reference <- function(result, tree) {
  .sx_geometry(tree)
  expected <- validate_species_tree(tree)$coordinates
  cols <- c("coordinate_id", "canonical_split", "branch_type", "primitive_alias_text",
            "side_a_taxa", "side_b_taxa", "primitive_aliases")
  .sx_need(identical(result$primitive_coordinates[, cols, drop = FALSE], expected[, cols, drop = FALSE]),
           "wrong reference tree or native ordered label ledger for this result")
  primitive <- result$primitive_coordinates
  domain_hash <- .sx_hash(sort(.sx_utf8(tree$tip.label), method = "radix"))
  coordinate_id <- vapply(primitive$canonical_split, function(key)
    paste0("SAR2:", .sx_hash(list(schema = result$metadata$split_key_schema,
                               taxon_domain_sha256 = domain_hash, canonical_key = .sx_utf8(key)))), character(1))
  terminal <- vapply(seq_len(nrow(primitive)), function(i) {
    if (primitive$branch_type[[i]] != "terminal") return(NA_character_)
    side <- if (length(primitive$side_a_taxa[[i]]) == 1L) primitive$side_a_taxa[[i]] else primitive$side_b_taxa[[i]]
    .sx_need(length(side) == 1L, "terminal split has no unique singleton taxon")
    side[[1L]]
  }, character(1))
  coordinates <- data.frame(coordinate_id = unname(coordinate_id),
                            canonical_split_key = primitive$canonical_split,
                            key_schema = result$metadata$split_key_schema,
                            source_alias = primitive$coordinate_id,
                            coordinate_type = "primitive", branch_type = primitive$branch_type,
                            terminal_taxon = terminal, side_A_taxa = I(primitive$side_a_taxa),
                            side_B_taxa = I(primitive$side_b_taxa),
                            representation_aliases = I(primitive$primitive_aliases),
                            stringsAsFactors = FALSE, check.names = FALSE)
  list(coordinates = coordinates, taxon_domain_sha256 = domain_hash)
}

.sx_producer <- function(producer) {
  .sx_fields(producer, c("source_commit", "source_tree", "source_parent", "dirty_scope",
                         "source_files", "provenance_status"), "producer provenance")
  .sx_need(all(vapply(producer[c("source_commit", "source_tree", "source_parent")],
                     function(v) .sx_string(v) && grepl("^[0-9a-f]{40}$", v), logical(1))), "producer base identities must be full Git hashes")
  .sx_need(producer$provenance_status %in% c("development_unreleased", "synthetic_fixture") &&
             .sx_string(producer$provenance_status), "unknown producer provenance status")
  .sx_need(is.character(producer$dirty_scope) && !anyNA(producer$dirty_scope) &&
             !anyDuplicated(producer$dirty_scope), "invalid producer dirty scope")
  .sx_need(is.character(producer$source_files) && .sx_keys(names(producer$source_files)) &&
             all(grepl("^[0-9a-f]{64}$", producer$source_files)), "producer source file manifest requires named full SHA-256 identities")
  invisible(producer)
}

.sx_source <- function(source, tree, stored = FALSE) {
  .sx_need(is.list(source) && .sx_string(source$kind) && .sx_string(source$id), "tree_source kind and explicit id are required")
  if (!stored) {
    if (identical(source$kind, "provided_phylo")) {
      .sx_fields(source, c("kind", "id"), "provided phylo source")
      return(source)
    }
    if (identical(source$kind, "newick_text")) {
      .sx_fields(source, c("kind", "id", "text"), "Newick source")
      .sx_need(.sx_string(source$text), "Newick source text is required")
      bytes <- charToRaw(.sx_utf8(source$text))
      source <- list(kind = source$kind, id = source$id, bytes = bytes, sha256 = .sx_raw_hash(bytes))
    } else if (identical(source$kind, "file")) {
      .sx_fields(source, c("kind", "id", "path"), "tree file source")
      .sx_need(.sx_string(source$path) && file.exists(source$path) && !dir.exists(source$path), "tree source file is missing")
      bytes <- readBin(source$path, "raw", n = file.info(source$path)$size)
      source <- list(kind = source$kind, id = source$id, path = normalizePath(source$path),
                     bytes = bytes, sha256 = .sx_raw_hash(bytes))
    } else .sx_need(FALSE, "unknown tree source provenance kind")
  }
  if (identical(source$kind, "provided_phylo")) {
    .sx_fields(source, c("kind", "id"), "provided phylo source"); return(source)
  }
  .sx_need(source$kind %in% c("newick_text", "file"), "unknown stored tree provenance")
  .sx_fields(source, c("kind", "id", if (source$kind == "file") "path", "bytes", "sha256"), "stored tree source")
  .sx_need(is.raw(source$bytes) && identical(.sx_raw_hash(source$bytes), source$sha256), "tree source bytes/hash mismatch")
  from_source <- ape::read.tree(text = rawToChar(source$bytes))
  fields <- c("edge", "tip.label", "Nnode", "edge.length", "node.label", "root.edge")
  .sx_need(all(vapply(fields, function(n) identical(from_source[[n]], tree[[n]]), logical(1))),
           "source tree bytes disagree with explicitly supplied phylo instance")
  source
}

.sx_payload <- function(payload) {
  .sx_fields(payload, c("type", "name", "units", "scale", "origin", "spec_id"), "payload")
  .sx_need(all(vapply(payload, .sx_string, logical(1))) && payload$type == "branch_length" &&
             payload$scale == "identity", "unsupported payload type/scale; profile accepts primitive branch_length on identity scale")
  invisible(payload)
}
.sx_data <- function(result, coordinates) {
  ids <- coordinates$source_alias; genes <- rownames(result$state_matrix)
  axis <- list(genes, coordinates$coordinate_id)
  values <- result$numeric_matrix[, ids, drop = FALSE]; dimnames(values) <- axis
  source_state <- result$state_matrix; dimnames(source_state) <- axis
  field <- function(name) matrix(as.character(result$state_ledger[[name]]), nrow = length(genes),
                                  byrow = TRUE, dimnames = axis)
  source_reason <- field("reason_code"); numeric_status <- field("numeric_status")
  state <- source_state; state[state == "mapped"] <- "observed"
  reason <- matrix(NA_character_, nrow(values), ncol(values), dimnames = axis)
  missing <- source_state == "mapped" & is.na(values)
  .sx_need(!any(is.nan(values) | is.infinite(values)), "NaN/Inf values are unsupported")
  .sx_need(all(numeric_status[missing] %in% c("missing_branch_length", "software_failure_marker")),
           "mapped-unavailable value needs a supported explicit numeric reason")
  reason[missing] <- numeric_status[missing]
  list(values = values, coord_state = state, value_reason = reason, source_state = source_state,
       source_reason = source_reason, numeric_status = numeric_status)
}
.sx_seal <- function(x) {
  hashes <- vapply(x[.sx_components], .sx_hash, character(1))
  x$manifest <- list(hash_schema = .sx_hash_schema, component_sha256 = hashes,
                     content_sha256 = .sx_hash(hashes))
  x
}
.sx_label_ledger <- function(coordinates, scheme, aliases = coordinates$source_alias) {
  .sx_scheme(scheme)
  .sx_need(.sx_keys(aliases) && length(aliases) == nrow(coordinates) && all(grepl("^B[1-9][0-9]*$", aliases)),
           "label aliases must be unique B strings within their scheme")
  data.frame(coordinate_id = coordinates$coordinate_id, alias = aliases,
             scheme_id = scheme$id, scheme_version = scheme$version,
             stringsAsFactors = FALSE, check.names = FALSE)
}

#' Export a versioned primitive exchange envelope
#' @param result A single fixed-mode splitaligner_result.
#' @param species_tree Explicit complete ape phylo used for this result.
#' @param tree_source Explicit source list; see the exchange API specification.
#' @param producer Declared development source identities and file hashes.
#' @param label_scheme Explicit registered list(id, version); native scheme required.
#' @param payload Explicit branch_length metadata (type/name/units/scale/origin/spec_id).
#' @param file Optional new RDS destination; an existing path is rejected.
#' @param branch_margin 2 for gene by branch, or explicitly 1 for branch by gene.
#' @return A validated splitaligner_exchange, also saved when file is provided.
#' @export
export_splitaligner_exchange <- function(result, species_tree, tree_source, producer,
                                         label_scheme, payload, file = NULL, branch_margin = 2L) {
  .sx_need(!inherits(result, "splitaligner_paired_result"), "paired results are unsupported by this profile")
  validate_splitaligner_result_object(result)
  .sx_need(identical(result$metadata$mode, "fixed"), "only single fixed mode is supported; free/unknown mode rejected")
  .sx_producer(producer); .sx_scheme(label_scheme); .sx_payload(payload)
  .sx_need(identical(label_scheme, .sx_native_scheme), "export requires explicit native scheme; historical conversion requires migration authority")
  .sx_need(length(branch_margin) == 1L && branch_margin %in% c(1L, 2L), "branch_margin must be explicitly 1 or 2")
  reference <- .sx_reference(result, species_tree); coordinates <- reference$coordinates
  ledger <- .sx_label_ledger(coordinates, label_scheme)
  source <- .sx_source(tree_source, species_tree)
  taxon_ledger <- data.frame(position = seq_along(species_tree$tip.label), taxon = species_tree$tip.label,
                             stringsAsFactors = FALSE)
  identity <- list(coordinate_system_id = paste0("SAR-CS2:", .sx_hash(list(
    taxon_domain_sha256 = reference$taxon_domain_sha256,
    coordinate_ids = sort(coordinates$coordinate_id, method = "radix")))),
    taxon_domain_sha256 = reference$taxon_domain_sha256,
    reference_tree_sha256 = .sx_hash(species_tree),
    ordered_branch_ledger_sha256 = .sx_hash(coordinates),
    ordered_taxon_ledger_sha256 = .sx_hash(taxon_ledger),
    ordered_label_ledger_sha256 = .sx_hash(ledger))
  x <- list(schema = list(id = "SplitAlignerR.exchange", version = .sx_version, profile = .sx_profile),
            producer = list(package = "SplitAlignerR", version = as.character(utils::packageVersion("SplitAlignerR")),
                            core_version = result$metadata$core_version, source = producer),
            contract = list(mode = "fixed", payload = payload, state_schema = "LT-compatible-observed-plus-structural-v1",
                            source_state_schema = result$metadata$state_schema,
                            split_key_schema = result$metadata$split_key_schema,
                            numeric_policy = "finite-double-v1; negative finite values preserved; LT S2 admission is separate"),
            axes = list(orientation = "gene_by_branch", branch_margin = 2L,
                        gene_ids = rownames(result$state_matrix), coordinate_ids = coordinates$coordinate_id),
            identity = identity,
            tree = list(phylo = species_tree, source = source, ordered_taxon_ledger = taxon_ledger),
            coordinates = coordinates,
            labels = list(registry_version = .sx_version, native_scheme = label_scheme,
                          native_ledger = ledger, active_scheme = label_scheme, active_ledger = ledger,
                          migrations = list()),
            data = .sx_data(result, coordinates),
            preserved = list(result = result, composite_values = result$numeric_matrix[, result$composite_coordinates$coordinate_id, drop = FALSE],
                             composite_coordinates = result$composite_coordinates,
                             composite_ledger = result$composite_ledger, state_ledger = result$state_ledger,
                             gene_provenance = result$gene_provenance),
            annotation = .sx_tree_map(species_tree, coordinates, ledger))
  class(x) <- c("splitaligner_exchange", "list"); x <- .sx_seal(x)
  if (branch_margin == 1L) x <- transpose_splitaligner_exchange(x)
  validate_splitaligner_exchange(x)
  if (!is.null(file)) {
    .sx_need(.sx_string(file) && dir.exists(dirname(file)) && !file.exists(file), "RDS output must be a new file in an existing directory")
    saveRDS(x, file, version = 3L)
  }
  x
}

#' Validate a versioned exchange envelope without guessing axes or state
#' @param x A splitaligner_exchange object.
#' @return Invisibly x, or an error on mismatch.
#' @export
validate_splitaligner_exchange <- function(x) {
  .sx_need(inherits(x, "splitaligner_exchange"), "object is not a splitaligner_exchange")
  .sx_fields(x, c(.sx_components, "manifest"), "exchange")
  .sx_need(identical(x$schema, list(id = "SplitAlignerR.exchange", version = .sx_version, profile = .sx_profile)), "unknown exchange schema/profile")
  hashes <- vapply(x[.sx_components], .sx_hash, character(1))
  .sx_need(identical(x$manifest, list(hash_schema = .sx_hash_schema, component_sha256 = hashes,
                                    content_sha256 = .sx_hash(hashes))), "component or manifest hash mismatch")
  result <- x$preserved$result; validate_splitaligner_result_object(result)
  .sx_need(identical(result$metadata$mode, "fixed") && identical(x$contract$mode, "fixed"), "unsupported mode")
  .sx_payload(x$contract$payload); .sx_producer(x$producer$source)
  .sx_need(identical(x$contract, list(mode = "fixed", payload = x$contract$payload,
    state_schema = "LT-compatible-observed-plus-structural-v1",
    source_state_schema = result$metadata$state_schema, split_key_schema = result$metadata$split_key_schema,
    numeric_policy = "finite-double-v1; negative finite values preserved; LT S2 admission is separate")),
    "unknown state/split/numeric contract metadata")
  .sx_fields(x$producer, c("package", "version", "core_version", "source"), "producer")
  .sx_fields(x$tree, c("phylo", "source", "ordered_taxon_ledger"), "tree envelope")
  .sx_fields(x$labels, c("registry_version", "native_scheme", "native_ledger", "active_scheme", "active_ledger", "migrations"), "label registry envelope")
  .sx_need(identical(x$producer$package, "SplitAlignerR") && .sx_string(x$producer$version) &&
             identical(x$producer$core_version, result$metadata$core_version), "unknown producer identity")
  reference <- .sx_reference(result, x$tree$phylo)
  .sx_need(identical(x$coordinates, reference$coordinates), "coordinate identity/ledger mismatch")
  .sx_source(x$tree$source, x$tree$phylo, stored = TRUE)
  expected_taxa <- data.frame(position = seq_along(x$tree$phylo$tip.label), taxon = x$tree$phylo$tip.label, stringsAsFactors = FALSE)
  .sx_need(identical(x$tree$ordered_taxon_ledger, expected_taxa), "ordered taxon ledger mismatch")
  .sx_need(identical(x$labels$registry_version, .sx_version) && identical(x$labels$native_scheme, .sx_native_scheme), "unknown label registry/native provenance")
  .sx_need(identical(x$labels$native_ledger, .sx_label_ledger(x$coordinates, .sx_native_scheme)), "wrong native label ledger")
  .sx_validate_label_history(x)
  expected_identity <- list(coordinate_system_id = paste0("SAR-CS2:", .sx_hash(list(
    taxon_domain_sha256 = reference$taxon_domain_sha256,
    coordinate_ids = sort(x$coordinates$coordinate_id, method = "radix")))),
    taxon_domain_sha256 = reference$taxon_domain_sha256,
    reference_tree_sha256 = .sx_hash(x$tree$phylo), ordered_branch_ledger_sha256 = .sx_hash(x$coordinates),
    ordered_taxon_ledger_sha256 = .sx_hash(expected_taxa), ordered_label_ledger_sha256 = .sx_hash(x$labels$active_ledger))
  .sx_need(identical(x$identity, expected_identity), "wrong tree or ordered ledger identity")
  expected <- .sx_data(result, x$coordinates)
  .sx_need(x$axes$branch_margin %in% c(1L, 2L) && length(x$axes$branch_margin) == 1L, "unknown branch margin")
  if (x$axes$branch_margin == 1L) expected <- lapply(expected, t)
  .sx_need(identical(x$axes, list(orientation = if (x$axes$branch_margin == 2L) "gene_by_branch" else "branch_by_gene",
                                 branch_margin = as.integer(x$axes$branch_margin), gene_ids = rownames(result$state_matrix),
                                 coordinate_ids = x$coordinates$coordinate_id)), "unknown or mismatched ordered axes")
  .sx_need(identical(x$data, expected), "values/state/reasons/axes must agree with the full preserved result")
  expected_preserved <- list(result = result, composite_values = result$numeric_matrix[, result$composite_coordinates$coordinate_id, drop = FALSE],
                             composite_coordinates = result$composite_coordinates, composite_ledger = result$composite_ledger,
                             state_ledger = result$state_ledger, gene_provenance = result$gene_provenance)
  .sx_need(identical(x$preserved, expected_preserved), "composite/state/gene ledgers were lost or mixed with ordinary edges")
  .sx_need(identical(x$annotation, .sx_tree_map(x$tree$phylo, x$coordinates, x$labels$active_ledger)), "annotation belongs to the wrong tree instance or label ledger")
  invisible(x)
}

#' Read a checked versioned exchange RDS
#' @param file Existing versioned RDS envelope.
#' @return A validated splitaligner_exchange.
#' @export
read_splitaligner_exchange <- function(file) {
  .sx_need(.sx_string(file) && file.exists(file) && !dir.exists(file), "exchange RDS file is missing")
  x <- readRDS(file); validate_splitaligner_exchange(x); x
}

#' Transpose all synchronized exchange arrays explicitly
#' @param x A validated exchange object.
#' @return A transposed envelope with new array manifest hashes.
#' @export
transpose_splitaligner_exchange <- function(x) {
  validate_splitaligner_exchange(x)
  x$data <- lapply(x$data, t); x$axes$branch_margin <- 3L - x$axes$branch_margin
  x$axes$orientation <- if (x$axes$branch_margin == 2L) "gene_by_branch" else "branch_by_gene"
  x <- .sx_seal(x); validate_splitaligner_exchange(x); x
}

#' Annotate the edges of an explicitly specified display tree instance
#' @param x A validated exchange envelope.
#' @param gene_id One exact gene key; composites are never ordinary edges.
#' @param tree Explicit display phylo; defaults to the preserved reference.
#' @return One row per edge, with separate tree geometry and selected gene values.
#' @export
annotate_splitaligner_exchange <- function(x, gene_id, tree = x$tree$phylo) {
  validate_splitaligner_exchange(x)
  .sx_need(.sx_string(gene_id) && gene_id %in% x$axes$gene_ids, "select one exact gene_id")
  out <- .sx_tree_map(tree, x$coordinates, x$labels$active_ledger)$edges
  data <- if (x$axes$branch_margin == 2L) x$data else lapply(x$data, t)
  out$gene_id <- gene_id
  out$gene_branch_value <- as.numeric(data$values[gene_id, out$coordinate_id])
  for (field in c("coord_state", "value_reason", "source_state", "source_reason", "numeric_status"))
    out[[field]] <- as.character(data[[field]][gene_id, out$coordinate_id])
  out$label_scheme <- x$labels$active_scheme$id
  out$label_scheme_version <- x$labels$active_scheme$version
  out
}
