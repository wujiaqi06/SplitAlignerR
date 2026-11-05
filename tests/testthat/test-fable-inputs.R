test_that("named explicit gene IDs make valid result axes", {
  species <- "((A,B),(C,D));"
  trees <- c(first = species, second = species)
  ids <- vapply(names(trees), toupper, character(1))
  result <- align_branches(species, trees, gene_ids = ids)
  expect_identical(rownames(result$state_matrix), c("FIRST", "SECOND"))
  expect_identical(result$input$gene_ids, c("FIRST", "SECOND"))
  expect_no_error(free_fusion_groups(result))
})

test_that("phylo input preserves tip identity, precise lengths and missing evidence", {
  species <- "(('A one','O''Brien'),('C,1','D):;'));"
  newick <- "(('A one':0.123456789012345,'O''Brien'):2,('C,1':NaN,'D):;':3):4);"
  phy <- ape::read.tree(text = "((A:1,B:1):2,(C:1,D:3):4);")
  phy$tip.label <- c("A one", "O'Brien", "C,1", "D):;")
  terminal_edges <- match(seq_along(phy$tip.label), phy$edge[, 2])
  phy$edge.length[terminal_edges] <- c(0.123456789012345, NA_real_, NaN, 3)
  # Compressed multiPhylo objects store their tip labels once on the container.
  compressed <- phy
  compressed$tip.label <- NULL
  multi <- structure(list(g = compressed), TipLabel = phy$tip.label, class = "multiPhylo")
  expected <- align_branches(species, newick, gene_ids = "g")
  for (input in list(phy, list(g = phy), multi)) {
    aligned <- align_branches(species, input, gene_ids = "g")
    expect_identical(aligned$state_matrix, expected$state_matrix)
    expect_identical(aligned$numeric_matrix, expected$numeric_matrix)
    expect_identical(aligned$gene_provenance, expected$gene_provenance)
    expect_identical(aligned$diagnostics, expected$diagnostics)
  }
  expect_identical(validate_species_tree(phy)$coordinates,
                   validate_species_tree(species)$coordinates)
})

test_that("gene file records accept Unicode letters and reject Newick punctuation in IDs", {
  species <- "((A,B),(C,D));"
  path <- tempfile(fileext = ".trees")
  on.exit(unlink(path))
  id <- "\u57fa\u56e0_\u03b1"
  writeLines(paste0(id, species), path, useBytes = TRUE)
  expect_identical(align_branches(species, path)$input$gene_ids, id)
  writeLines(paste0("bad;", species), path)
  expect_error(align_branches(species, path), "invalid ID prefix")
})

test_that("missing tree paths get a file diagnostic, while malformed Newick is parsed", {
  path <- tempfile(fileext = ".nwk")
  expect_error(validate_species_tree(path), "Tree file does not exist")
  expect_error(align_branches("((A,B),(C,D));", path), "Tree file does not exist")
  expect_error(validate_species_tree("(A/path,B)"), "Newick parse error")
})
