terminal_taxon_by_coordinate <- function(primitive_coordinates) {
  terminals <- subset(primitive_coordinates, branch_type == "terminal")
  vapply(seq_len(nrow(terminals)), function(i) {
    side_a <- terminals$side_a_taxa[[i]]
    side_b <- terminals$side_b_taxa[[i]]
    if (length(side_a) == 1L) side_a else side_b
  }, character(1), USE.NAMES = TRUE)
}

test_that("random induced trees produce no false topological absence", {
  for (seed in 1:24) {
    set.seed(seed)
    tip_count <- sample(5:12, 1L)
    species <- ape::rtree(tip_count)
    species$tip.label <- paste0("taxon_", seq_len(tip_count))
    retained_count <- sample(2:tip_count, 1L)
    retained <- sample(species$tip.label, retained_count)
    removed <- setdiff(species$tip.label, retained)
    gene <- if (length(removed)) ape::drop.tip(species, removed) else species

    aligned <- align_branches(species, gene, mode = "fixed")
    expect_false(any(aligned$state_matrix == "NA_topo"), info = paste("seed", seed))
    expect_identical(
      sum(subset(
        aligned$diagnostics,
        code == "FIXED_TOPOLOGY_MISMATCH"
      )$count),
      0L,
      info = paste("seed", seed)
    )
    terminal_map <- terminal_taxon_by_coordinate(
      aligned$primitive_coordinates
    )
    retained_coordinates <- names(terminal_map)[terminal_map %in% retained]
    expect_false(
      any(aligned$state_matrix[1L, retained_coordinates] == "NA_topo"),
      info = paste("terminal seed", seed)
    )
    expect_true(all(
      is.na(aligned$numeric_matrix) | is.finite(aligned$numeric_matrix)
    ))
  }
})

test_that("retained terminal splits never become NA_topo under discordance", {
  for (seed in 101:116) {
    set.seed(seed)
    tip_count <- sample(5:12, 1L)
    labels <- paste0("tip_", seq_len(tip_count))
    species <- ape::rtree(tip_count, tip.label = labels)
    gene <- ape::rtree(tip_count, tip.label = labels)

    aligned <- align_branches(species, gene, mode = "free")
    terminal_ids <- subset(
      aligned$primitive_coordinates,
      branch_type == "terminal"
    )$coordinate_id
    expect_true(
      all(aligned$state_matrix[1L, terminal_ids] == "mapped"),
      info = paste("seed", seed)
    )
  }
})

test_that("species root representation does not change split-key results", {
  rooted <- "((A:1,B:1):1,(C:1,(D:1,E:1):1):1);"
  unrooted <- "(A:1,B:1,(C:1,(D:1,E:1):1):1);"
  genes <- c(
    full = "(A:1,B:1,(C:1,(D:1,E:1):1):1);",
    pruned = "(A:1,B:1,(C:1,D:2):1);",
    discordant = "(A:1,C:1,(B:1,(D:1,E:1):1):1);"
  )
  a <- align_branches(rooted, genes)
  b <- align_branches(unrooted, genes)

  split_a <- setNames(
    a$primitive_coordinates$canonical_split,
    a$primitive_coordinates$coordinate_id
  )
  split_b <- setNames(
    b$primitive_coordinates$canonical_split,
    b$primitive_coordinates$coordinate_id
  )
  expect_identical(anyDuplicated(unname(split_a)), 0L)
  expect_identical(anyDuplicated(unname(split_b)), 0L)
  expect_setequal(unname(split_a), unname(split_b))
  for (gene in rownames(a$state_matrix)) {
    state_a <- setNames(a$state_matrix[gene, ], split_a)
    state_b <- setNames(b$state_matrix[gene, ], split_b)
    expect_identical(state_a[sort(names(state_a))],
                     state_b[sort(names(state_b))])
  }
})

canonical_simple_split <- function(left, right) {
  left <- sort(left, method = "radix")
  right <- sort(right, method = "radix")
  left_text <- paste(left, collapse = "..")
  right_text <- paste(right, collapse = "..")
  if (left_text > right_text) {
    return(paste(right_text, left_text, sep = "||"))
  }
  paste(left_text, right_text, sep = "||")
}

restore_simple_split_labels <- function(key, inverse) {
  sides <- strsplit(key, "||", fixed = TRUE)[[1L]]
  taxa <- lapply(sides, strsplit, split = "..", fixed = TRUE)
  taxa <- lapply(taxa, `[[`, 1L)
  taxa <- lapply(taxa, function(side) unname(inverse[side]))
  canonical_simple_split(taxa[[1L]], taxa[[2L]])
}

test_that("production states are invariant to consistent tip relabeling", {
  for (seed in 201:212) {
    set.seed(seed)
    tip_count <- sample(5:10, 1L)
    labels <- paste0("t", seq_len(tip_count))
    species <- ape::rtree(tip_count, tip.label = labels)
    gene <- ape::rtree(tip_count, tip.label = labels)
    original <- align_branches(species, c(g = ape::write.tree(gene)))

    mapping <- stats::setNames(
      sprintf("z%02d", rev(seq_len(tip_count))), labels
    )
    inverse <- stats::setNames(names(mapping), unname(mapping))
    relabeled_species <- species
    relabeled_species$tip.label <- unname(mapping[species$tip.label])
    relabeled_gene <- gene
    relabeled_gene$tip.label <- unname(mapping[gene$tip.label])
    relabeled <- align_branches(
      relabeled_species, c(g = ape::write.tree(relabeled_gene))
    )

    original_state <- stats::setNames(
      original$state_matrix[1L, ],
      original$primitive_coordinates$canonical_split
    )
    restored_keys <- vapply(
      relabeled$primitive_coordinates$canonical_split,
      restore_simple_split_labels,
      character(1),
      inverse = inverse
    )
    relabeled_state <- stats::setNames(
      relabeled$state_matrix[1L, ], restored_keys
    )
    expect_identical(
      original_state[sort(names(original_state))],
      relabeled_state[sort(names(relabeled_state))],
      info = paste("seed", seed)
    )
  }
})

test_that("valid restriction never emits an endpoint-collapse fallback", {
  for (seed in 301:324) {
    set.seed(seed)
    species <- ape::rtree(10L, tip.label = paste0("t", 1:10))
    retained <- sample(species$tip.label, sample(2:9, 1L))
    gene <- ape::drop.tip(species, setdiff(species$tip.label, retained))
    aligned <- expect_no_error(align_branches(species, gene, mode = "fixed"))
    expect_false(
      any(aligned$state_ledger$reason_code == "ENDPOINT_COLLAPSED"),
      info = paste("seed", seed)
    )
  }

  multifurcating <- align_branches(
    "(((A,B),C),(D,E,F));",
    c(g = "((A,C),(D,E,F));"),
    mode = "fixed"
  )
  expect_false(any(
    multifurcating$state_ledger$reason_code == "ENDPOINT_COLLAPSED"
  ))
})

test_that("R wrapper preserves every production-core component", {
  species <- "((A:1,B:2):3,(C:4,D:5):6);"
  genes <- c(
    first = "((A:1,B:2):3,(C:4,D:5):6);",
    second = "((A:1,C:2):3,(B:4,D:5):6);"
  )
  wrapped <- align_branches(species, genes, mode = "free")
  raw <- cpp_align_branches(species, unname(genes), names(genes), "free")
  expect_identical(wrapped[names(raw)], raw)
})
