# Independent fixed-topology graph alignment.  This module never constructs a
# split or calls either mapping backend.  Edge identities stay on the reference
# graph while pruning and contraction carry their complete member sets forward.

.s4_stop <- function(message, gene_id = NULL,
                     code = "INVALID_TREE", mismatch = FALSE) {
  condition <- structure(
    list(message = message, call = NULL, gene_id = gene_id, code = code),
    class = c(if (mismatch) "splitaligner_topology_mismatch" else
                "splitaligner_invalid_tree", "error", "condition")
  )
  stop(condition)
}

.s4_b_order <- function(ids) {
  order(as.numeric(sub("^B", "", ids)), ids, method = "radix")
}

.s4_byte_key <- function(label) {
  paste(sprintf("%02x", as.integer(charToRaw(enc2utf8(label)))), collapse = "")
}

.s4_incident <- function(graph, node) {
  edges <- graph$adjacency[[node]]
  edges[graph$active[edges]]
}

.s4_other <- function(graph, edge, node) {
  ifelse(graph$u[edge] == node, graph$v[edge], graph$u[edge])
}

.s4_snapshot <- function(graph) {
  as.list.environment(graph, all.names = TRUE)
}

.s4_graph <- function(parsed, reference = FALSE, gene_id = NULL) {
  n <- length(parsed$parent)
  parent <- parsed$parent
  root <- parsed$root
  if (n < 3L || length(root) != 1L || is.na(root) || root < 1L ||
      root > n || length(parsed$labels) != n || length(parsed$tip) != n ||
      anyNA(parent) || any(parent < 0L | parent > n) ||
      any(parent != as.integer(parent)) ||
      sum(parent == 0L) != 1L || parent[[root]] != 0L ||
      any(parent == seq_len(n)) || anyNA(parsed$tip)) {
    .s4_stop("Malformed parsed tree graph.", gene_id)
  }
  labels <- as.character(parsed$labels)
  tips <- as.logical(parsed$tip)
  if (anyNA(labels[tips]) || any(!nzchar(labels[tips])) ||
      anyDuplicated(enc2utf8(labels[tips]))) {
    .s4_stop("Tree tip labels must be nonempty and unique.", gene_id)
  }
  if (sum(tips) < 2L || any(tabulate(parent[parent > 0L], n)[tips] > 0L)) {
    .s4_stop("A tree needs at least two leaf taxa.", gene_id)
  }
  child <- which(parent > 0L)
  if (length(parsed$lengths) != n || length(parsed$numeric_status) != n ||
      length(parsed$source_nodes) != n ||
      (reference && length(parsed$branch_id) != n)) {
    .s4_stop("Malformed parsed tree edge metadata.", gene_id)
  }
  graph <- new.env(parent = emptyenv())
  graph$u <- as.integer(parent[child])
  graph$v <- as.integer(child)
  graph$root <- as.integer(root)
  graph$gene_id <- gene_id
  graph$root_promoted <- FALSE
  graph$removed_root_members <- character()
  graph$tip <- tips
  graph$labels <- labels
  graph$alive <- rep(TRUE, n)
  graph$active <- rep(TRUE, length(child))
  graph$adjacency <- vector("list", n)
  for (edge in seq_along(child)) {
    a <- graph$u[[edge]]
    b <- graph$v[[edge]]
    graph$adjacency[[a]] <- c(graph$adjacency[[a]], edge)
    graph$adjacency[[b]] <- c(graph$adjacency[[b]], edge)
  }
  graph$members <- if (reference) as.list(parsed$branch_id[child]) else
    rep(list(character()), length(child))
  if (reference && (anyNA(parsed$branch_id[child]) ||
                    any(!grepl("^B[1-9][0-9]*$", parsed$branch_id[child])) ||
                    anyDuplicated(parsed$branch_id[child]))) {
    .s4_stop("Reference branch IDs must be unique B-number identifiers.", gene_id)
  }
  graph$sources <- lapply(parsed$source_nodes[child], as.integer)
  graph$value <- if (reference) rep(NA_real_, length(child)) else
    as.numeric(parsed$lengths[child])
  graph$status <- if (reference) rep("missing_branch_length", length(child)) else
    as.character(parsed$numeric_status[child])
  valid_status <- c("finite_numeric", "missing_branch_length",
                    "software_failure_marker")
  if (anyNA(graph$status) || any(!graph$status %in% valid_status) ||
      any(graph$status == "finite_numeric" & !is.finite(graph$value))) {
    .s4_stop("Inconsistent parsed branch length status.", gene_id)
  }
  # Validate connectivity before graph surgery; parser node numbers themselves
  # are local addresses, never identities shared between the two trees.
  .s4_orient(graph, graph$root, gene_id)
  graph
}

.s4_remove_edge <- function(graph, edge) {
  graph$active[[edge]] <- FALSE
  invisible(NULL)
}

.s4_contract <- function(graph, node) {
  edges <- .s4_incident(graph, node)
  if (length(edges) != 2L || graph$tip[[node]]) {
    stop("Internal S4 error: invalid degree-two contraction.", call. = FALSE)
  }
  first <- edges[[1L]]
  second <- edges[[2L]]
  a <- .s4_other(graph, first, node)
  b <- .s4_other(graph, second, node)
  graph$u[[first]] <- a
  graph$v[[first]] <- b
  graph$members[[first]] <- unique(c(graph$members[[first]],
                                   graph$members[[second]]))
  graph$sources[[first]] <- sort(unique(c(graph$sources[[first]],
                                        graph$sources[[second]])))
  status <- graph$status[edges]
  if (any(status == "software_failure_marker")) {
    graph$status[[first]] <- "software_failure_marker"
    graph$value[[first]] <- NA_real_
  } else if (any(status == "missing_branch_length")) {
    graph$status[[first]] <- "missing_branch_length"
    graph$value[[first]] <- NA_real_
  } else {
    value <- sum(graph$value[edges])
    if (!is.finite(value)) {
      .s4_stop("Branch length sum exceeds the finite numeric range during contraction.",
               graph$gene_id, code = "NUMERIC_RANGE_ERROR")
    }
    graph$value[[first]] <- value
    graph$status[[first]] <- "finite_numeric"
  }
  graph$active[[second]] <- FALSE
  graph$alive[[node]] <- FALSE
  if (!first %in% graph$adjacency[[a]]) {
    graph$adjacency[[a]] <- c(graph$adjacency[[a]], first)
  }
  if (!first %in% graph$adjacency[[b]]) {
    graph$adjacency[[b]] <- c(graph$adjacency[[b]], first)
  }
  # If the representation root was contracted, keep a live temporary anchor.
  if (graph$root == node) graph$root <- a
  invisible(NULL)
}

.s4_prune <- function(graph, retained, semantics, root_policy = "mrca") {
  # Strip deleted leaves and dangling unlabeled vertices using a queue.  In a
  # rooted tree the root is protected here; its unary stem is handled below.
  queue <- which(graph$tip & !graph$labels %in% retained)
  next_item <- 1L
  while (next_item <= length(queue)) {
    node <- queue[[next_item]]
    next_item <- next_item + 1L
    if (!graph$alive[[node]]) next
    incident <- .s4_incident(graph, node)
    if (length(incident) > 1L) next
    if (graph$tip[[node]] && graph$labels[[node]] %in% retained) next
    if (semantics == "rooted" && node == graph$root) next
    graph$alive[[node]] <- FALSE
    if (length(incident)) {
      neighbor <- .s4_other(graph, incident, node)
      .s4_remove_edge(graph, incident)
      if (!graph$tip[[neighbor]]) queue <- c(queue, neighbor)
    }
  }
  .s4_normalize(graph, semantics, root_policy = root_policy)
  invisible(NULL)
}

.s4_normalize <- function(graph, semantics, root_policy = "mrca") {
  root_policy <- match.arg(root_policy, c("mrca", "preserve"))
  if (semantics == "rooted" && root_policy == "mrca") {
    # Standard rooted restriction retains the MRCA of surviving tips.  Edges
    # above that MRCA are stems, not coordinates of the restricted rooted tree.
    repeat {
      root <- graph$root
      edges <- .s4_incident(graph, root)
      if (graph$tip[[root]] || length(edges) != 1L) break
      graph$root_promoted <- TRUE
      graph$removed_root_members <- unique(c(graph$removed_root_members,
                                             graph$members[[edges]]))
      graph$root <- as.integer(.s4_other(graph, edges, root))
      graph$alive[[root]] <- FALSE
      .s4_remove_edge(graph, edges)
    }
  } else if (semantics == "unrooted") {
    # An unrooted Newick may also have a unary representation stem.
    queue <- which(graph$alive & !graph$tip)
    next_item <- 1L
    while (next_item <= length(queue)) {
      node <- queue[[next_item]]
      next_item <- next_item + 1L
      edges <- .s4_incident(graph, node)
      if (graph$alive[[node]] && length(edges) == 1L) {
        neighbor <- .s4_other(graph, edges, node)
        graph$alive[[node]] <- FALSE
        .s4_remove_edge(graph, edges)
        if (graph$root == node) graph$root <- as.integer(neighbor)
        if (!graph$tip[[neighbor]]) queue <- c(queue, neighbor)
      }
    }
  }
  # Removing a degree-two vertex does not change the degrees of its neighbors.
  for (node in which(graph$alive & !graph$tip)) {
    if (semantics == "rooted" && node == graph$root) next
    if (length(.s4_incident(graph, node)) == 2L) .s4_contract(graph, node)
  }
  invisible(NULL)
}

.s4_orient <- function(graph, root, gene_id = NULL) {
  n <- length(graph$alive)
  parent <- integer(n)
  incoming <- integer(n)
  children <- vector("list", n)
  order <- integer(sum(graph$alive))
  stack <- integer(n)
  stack[[1L]] <- root
  size <- 1L
  seen <- rep(FALSE, n)
  seen[[root]] <- TRUE
  count <- 0L
  while (size > 0L) {
    node <- stack[[size]]
    size <- size - 1L
    count <- count + 1L
    order[[count]] <- node
    for (edge in .s4_incident(graph, node)) {
      neighbor <- .s4_other(graph, edge, node)
      if (neighbor == parent[[node]]) next
      if (seen[[neighbor]] || !graph$alive[[neighbor]]) {
        .s4_stop("Tree graph contains a cycle or invalid edge.", gene_id)
      }
      seen[[neighbor]] <- TRUE
      parent[[neighbor]] <- node
      incoming[[neighbor]] <- edge
      children[[node]] <- c(children[[node]], neighbor)
      size <- size + 1L
      stack[[size]] <- neighbor
    }
  }
  if (count != sum(graph$alive)) {
    .s4_stop("Tree graph is disconnected.", gene_id)
  }
  list(root = root, parent = parent, incoming = incoming,
       children = children, order = order)
}

.s4_signatures <- function(graph, oriented, intern) {
  signatures <- integer(length(graph$alive))
  for (node in rev(oriented$order)) {
    child_ids <- sort(signatures[oriented$children[[node]]])
    label <- if (graph$tip[[node]])
      paste0("L", .s4_byte_key(graph$labels[[node]])) else "I"
    key <- paste0(label, "(", paste(child_ids, collapse = ","), ")")
    if (!exists(key, envir = intern, inherits = FALSE)) {
      intern$.next_id <- intern$.next_id + 1L
      assign(key, intern$.next_id, envir = intern)
    }
    signatures[[node]] <- get(key, envir = intern, inherits = FALSE)
  }
  signatures
}

.s4_reference <- function(parsed, semantics) {
  semantics <- match.arg(semantics, c("rooted", "unrooted"))
  graph <- .s4_graph(parsed, reference = TRUE)
  # Keep the original-reference input domain unchanged: accepting subdivided
  # reference edges here would create fusion states before any taxa are lost.
  # Unary roots created later by preserve-root restriction are still valid,
  # and gene inputs may explicitly represent those retained stems.
  child_count <- tabulate(parsed$parent[parsed$parent > 0L], length(parsed$parent))
  if (any(child_count[!parsed$tip] < 2L)) {
    .s4_stop(paste0("An original reference tree must have at least two children",
                    " at every internal node, including its root; unary nodes",
                    " are supported only in gene input representations."))
  }
  if (semantics == "unrooted") .s4_normalize(graph, semantics)
  edge_ids <- which(graph$active)
  # Degree-two aliases describe a single original unrooted edge.  Freeze its
  # canonical primitive once, rather than inventing a fusion of the two halves.
  aliases <- lapply(edge_ids, function(edge) {
    ids <- graph$members[[edge]]
    ids[.s4_b_order(ids)]
  })
  ids <- vapply(aliases, `[[`, character(1), 1L)
  positions <- .s4_b_order(ids)
  edge_ids <- edge_ids[positions]
  aliases <- aliases[positions]
  ids <- ids[positions]
  primitives <- data.frame(
    branch_id = ids,
    branch_type = ifelse(graph$tip[graph$u[edge_ids]] |
                          graph$tip[graph$v[edge_ids]], "terminal", "internal"),
    stringsAsFactors = FALSE
  )
  primitives$aliases <- I(aliases)
  primitives$source_nodes <- I(graph$sources[edge_ids])
  for (i in seq_along(edge_ids)) graph$members[[edge_ids[[i]]]] <- ids[[i]]
  taxa <- graph$labels[graph$tip & graph$alive]
  taxa <- taxa[order(vapply(taxa, .s4_byte_key, character(1)), method = "radix")]
  list(semantics = semantics, taxa = taxa, primitives = primitives,
       graph = .s4_snapshot(graph))
}

.s4_align_gene <- function(reference, parsed, gene_id) {
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
  ref <- list2env(reference$graph, parent = emptyenv())
  .s4_prune(ref, retained, reference$semantics)
  .s4_normalize(gene, reference$semantics)
  if (reference$semantics == "unrooted") {
    ref_root <- which(ref$alive & ref$tip & ref$labels == retained[[1L]])
    gene_root <- which(gene$alive & gene$tip & gene$labels == retained[[1L]])
  } else {
    ref_root <- ref$root
    gene_root <- gene$root
  }
  ref_order <- .s4_orient(ref, ref_root, gene_id)
  gene_order <- .s4_orient(gene, gene_root, gene_id)
  # Intern exact labeled child-multiset structures in a shared dictionary.
  # These integer signatures are collision-free identifiers, not hashes or
  # bipartitions, and their construction never uses branch lengths.
  intern <- new.env(hash = TRUE, parent = emptyenv())
  intern$.next_id <- 0L
  ref_sig <- .s4_signatures(ref, ref_order, intern)
  gene_sig <- .s4_signatures(gene, gene_order, intern)
  if (ref_sig[[ref_root]] != gene_sig[[gene_root]]) {
    .s4_stop(paste0("Gene tree '", gene_id,
                    "' does not match the restricted reference topology (",
                    reference$semantics, ")."), gene_id,
             code = "FIXED_TOPOLOGY_MISMATCH", mismatch = TRUE)
  }
  components <- vector("list", sum(ref$active))
  pairs <- list(c(ref_root, gene_root))
  next_pair <- 1L
  component_index <- 0L
  axis <- reference$primitives$branch_id
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
      members <- members[order(match(members, axis))]
      component_index <- component_index + 1L
      components[[component_index]] <- list(
        primitive_members = members,
        source_nodes = sort(gene$sources[[ge]]),
        reference_source_nodes = sort(ref$sources[[re]]),
        numeric_value = gene$value[[ge]],
        numeric_status = gene$status[[ge]]
      )
      pairs[[length(pairs) + 1L]] <- c(r, g)
    }
  }
  component_order <- order(vapply(components, function(component) {
    min(match(component$primitive_members, axis))
  }, integer(1)))
  list(retained_taxa = retained, components = components[component_order],
       root_promoted = ref$root_promoted,
       removed_root_members = ref$removed_root_members[
         order(match(ref$removed_root_members, axis))])
}
