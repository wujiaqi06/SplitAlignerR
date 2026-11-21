# Select a coordinate by its actual taxon split. The labels assigned by the
# R backend and the Fast CLI need not use the same ordering.
support_row_for_side <- function(result, side) {
  coords <- result$primitive_coordinates
  hit <- vapply(seq_len(nrow(coords)), function(i) {
    setequal(coords$side_a_taxa[[i]], side) || setequal(coords$side_b_taxa[[i]], side)
  }, logical(1))
  stopifnot(sum(hit) == 1L)
  table <- result$support_table
  table[match(coords$coordinate_id[hit], table$coordinate_id), , drop = FALSE]
}

test_that("default free and fixed results report hand-counted support on the reference branches", {
  reference <- "(((A:1,B:2)91:3,C:4)84:5,((D:6,E:7)99:8,(F:9,G:10)88:11)77:12);"
  free <- align_branches(reference, c(g1 = "(((A,C),B),((D,E),F));",
                                      g2 = "((A,C),D,((B,F),E));"))
  fixed_trees <- c(g1 = "(((A,B),C),((D,E),F));", g2 = "(((A,B),C),((D,E),F));")
  fixed <- align_branches(reference, fixed_trees, mode = "fixed")

  sides <- list(c("A", "B"), c("A", "B", "C"), c("D", "E"), c("F", "G"))
  for (mode in c("free", "fixed")) {
    result <- if (mode == "free") free else fixed
    recovered <- if (mode == "free") c(0, 1, 1, 0) else c(2, 2, 2, 0)
    expected_pct <- if (mode == "free") c(0, 50, 50, NA_real_) else c(100, 100, 100, NA_real_)
    table <- result$support_table
    expect_identical(table$coordinate_id, colnames(result$state_matrix))
    expect_equal(length(unique(table$coordinate_id)), 11L)
    expect_identical(table$branch_type, result$primitive_coordinates$branch_type)
    expect_true(all(table$n_valid_topologies == 2L))

    rows <- do.call(rbind, lapply(sides, function(side) support_row_for_side(result, side)))
    expect_equal(rows$n_dec, c(2, 2, 2, 0))
    expect_equal(rows$n_rec, recovered)
    expect_equal(rows$n_not_recovered, rows$n_dec - rows$n_rec)
    expect_equal(rows$n_fused, c(0, 0, 0, 2))
    expect_equal(rows$support_percent, expected_pct)
    expect_equal(rows$support_fraction, expected_pct / 100)
    # Both genes lack G. F's pendant edge is fused, while G is structurally absent.
    expect_equal(support_row_for_side(result, "G")$n_struct, 2)
    expect_equal(support_row_for_side(result, "F")$n_fused, 2)

    # Both halves of the middle split get its percentage. The F+G edge has no label.
    expected <- if (mode == "free") {
      "(((A:1,B:2)0:3,C:4)50:5,((D:6,E:7)50:8,(F:9,G:10):11)50:12);"
    } else {
      "(((A:1,B:2)100:3,C:4)100:5,((D:6,E:7)100:8,(F:9,G:10):11)100:12);"
    }
    observed_tree <- ape::read.tree(text = result$support_newick)
    expected_tree <- ape::read.tree(text = expected)
    expect_identical(observed_tree$node.label, expected_tree$node.label)
    expect_identical(observed_tree$tip.label, expected_tree$tip.label)
    expect_identical(observed_tree$edge, expected_tree$edge)
    expect_identical(observed_tree$edge.length, expected_tree$edge.length)
  }
})

test_that("a terminal-rooted reference preserves quoted tips and labels only the internal split", {
  reference <- "(A_one:1,('B, two':2,('C three':3,D:4)old:5)obsolete:6);"
  concordant <- "(A_one,'B, two',('C three',D));"
  discordant <- "(A_one,'C three',('B, two',D));"
  # A fixed label does not force recovery if the supplied tree has another topology.
  result <- align_branches(reference, c(concordant, concordant, discordant), mode = "fixed")
  row <- support_row_for_side(result, c("C three", "D"))
  expect_equal(row$n_rec, 2)
  expect_equal(row$n_dec, 3)
  expect_equal(row$support_percent, 100 * 2 / 3, tolerance = 0)
  tree <- ape::read.tree(text = result$support_newick)
  original <- ape::read.tree(text = reference)
  expect_identical(tree$tip.label, original$tip.label)
  expect_identical(tree$edge, original$edge)
  expect_identical(tree$edge.length, original$edge.length)
  labels <- tree$node.label[!is.na(tree$node.label) & nzchar(tree$node.label)]
  expect_length(labels, 1L)
  expect_identical(labels, sprintf("%.17g", row$support_percent))

  result_file <- tempfile(fileext = ".rds")
  output_dir <- tempfile()
  on.exit(unlink(c(result_file, output_dir), recursive = TRUE), add = TRUE)
  save_splitaligner_result(result, result_file)
  stored <- read_splitaligner_result(result_file)
  expect_identical(stored$support_table, result$support_table)
  expect_identical(stored$support_newick, result$support_newick)
  write_branch_support(stored, output_dir)
  expect_equal(readLines(file.path(output_dir, "support.nwk"), warn = FALSE),
               sub("[\r\n]+$", "", stored$support_newick))
  tsv <- read.delim(file.path(output_dir, "support.tsv"), colClasses = "character")
  expect_identical(tsv$coordinate_id, stored$support_table$coordinate_id)
  expect_identical(tsv$support_percent, sprintf("%.17g", stored$support_table$support_percent))
  expect_identical(tsv$support_percent[tsv$coordinate_id == row$coordinate_id], labels)
})

test_that("phylo names survive annotation and support exports reject incomplete or occupied targets", {
  reference <- ape::read.tree(text = "((Homo_sapiens,B),(C,D));")
  result <- align_branches(reference, list(g1 = reference), mode = "fixed")
  observed <- ape::read.tree(text = result$support_newick)
  expect_identical(observed$tip.label, reference$tip.label)
  expect_identical(observed$node.label, c("", "100", "100"))

  dest <- tempfile()
  on.exit(unlink(dest, recursive = TRUE), add = TRUE)
  damaged <- result
  damaged$support_newick <- NULL
  expect_error(write_branch_support(damaged, dest), "support|Support")
  expect_false(file.exists(dest))

  # Historical RDS objects remain readable, but lack the reference display
  # tree and the eligibility counts required to export support safely.
  old <- result
  old$support_newick <- NULL
  old$support_table <- NULL
  old$input$reference_newick <- NULL
  rds <- tempfile(fileext = ".rds")
  on.exit(unlink(rds), add = TRUE)
  saveRDS(old, rds)
  stored <- read_splitaligner_result(rds)
  expect_identical(stored$state_matrix, result$state_matrix)
  expect_error(write_branch_support(stored, dest), "align_branches")
  expect_false(file.exists(dest))

  dir.create(dest)
  sentinel <- file.path(dest, "support.nwk")
  writeLines("existing tree", sentinel)
  expect_error(write_branch_support(result, dest), "new directory")
  expect_identical(readLines(sentinel), "existing tree")
  expect_false(file.exists(file.path(dest, "support.tsv")))
})
