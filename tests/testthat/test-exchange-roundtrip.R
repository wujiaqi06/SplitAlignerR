test_that("fixed-mode exchange preserves tree, gene values and seals across a round trip", {
  ref <- ape::read.tree(text = "((A:5,B:6):7,C:8,D:9);")
  # A quoted tip must retain the same identity in the native and exchange paths.
  ref$tip.label[1L] <- "A one"
  result <- align_branches(ref, c(first = "(('A one':1,B:2):3,C:4,D:5);",
                                  second = "(('A one':6,B:7):8,C:9,D:10);"), mode = "fixed")
  producer <- list(source_commit = strrep("1", 40), source_tree = strrep("2", 40),
                   source_parent = strrep("3", 40), dirty_scope = character(),
                   source_files = c(fixture = strrep("4", 64)), provenance_status = "synthetic_fixture")
  payload <- list(type = "branch_length", name = "length", units = "substitutions/site",
                  scale = "identity", origin = "synthetic gene tree", spec_id = "roundtrip-test")
  path <- tempfile(fileext = ".rds")
  on.exit(unlink(path), add = TRUE)
  x <- export_splitaligner_exchange(result, ref, list(kind = "provided_phylo", id = "test"),
                                    producer, splitaligner_label_registry()$native$scheme,
                                    payload, file = path)
  saved <- read_splitaligner_exchange(path)
  expect_identical(saved, x)
  rotated <- transpose_splitaligner_exchange(saved)
  expect_identical(rotated$axes$orientation, "branch_by_gene")
  expect_identical(rotated$data$values, t(x$data$values))
  expect_identical(transpose_splitaligner_exchange(rotated), x)
  edges <- annotate_splitaligner_exchange(rotated, "second")
  a <- which(edges$terminal_taxon == "A one")
  expect_length(a, 1)
  expect_identical(edges$tree_branch_length[a], 5)
  expect_identical(edges$gene_branch_value[a], 6)
  saved$data$values[1, 1] <- -99
  expect_error(validate_splitaligner_exchange(saved), "hash mismatch")
})
