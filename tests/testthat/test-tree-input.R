test_that("C++ species-tree validation builds the frozen-style unrooted axis", {
  tree <- paste0(
    "((A:1,B:2)90[&support=90]:0.3,",
    "(C:4,D:5)88:0.4)root:9;"
  )
  validated <- validate_species_tree(tree)

  expect_s3_class(validated, "splitaligner_tree_validation")
  expect_true(validated$valid)
  expect_identical(validated$tip_labels, c("A", "B", "C", "D"))
  expect_identical(validated$metadata$tip_count, 4L)
  expect_identical(validated$metadata$primitive_alias_count, 6L)
  expect_identical(validated$metadata$coordinate_count, 5L)
  expect_identical(validated$metadata$root_degree, 2L)
  expect_identical(
    validated$coordinates$coordinate_id,
    paste0("B", 1:5)
  )
  expect_identical(
    validated$coordinates$primitive_alias_text[5],
    "B5|B6"
  )
  expect_identical(
    validated$coordinates$canonical_split[5],
    "A..B||C..D"
  )

  counts <- setNames(
    validated$diagnostics$count,
    validated$diagnostics$code
  )
  expect_identical(counts[["IGNORED_REFERENCE_BRANCH_LENGTH"]], 6L)
  expect_identical(counts[["IGNORED_ROOT_LENGTH"]], 1L)
  expect_identical(counts[["IGNORED_INTERNAL_LABEL"]], 3L)
  expect_identical(counts[["IGNORED_ANNOTATION_BLOCK"]], 1L)
  expect_identical(counts[["DUPLICATE_UNROOTED_SPLIT_ALIAS"]], 1L)
})

test_that("canonical split identity is invariant to representation root", {
  rooted <- validate_species_tree("((A:1,B:2):3,(C:4,D:5):6);")
  unrooted <- validate_species_tree("(A:1,B:2,(C:4,D:5):9);")

  expect_setequal(
    rooted$coordinates$canonical_split,
    unrooted$coordinates$canonical_split
  )
  expect_identical(rooted$metadata$coordinate_count, 5L)
  expect_identical(unrooted$metadata$coordinate_count, 5L)
  expect_identical(rooted$metadata$root_degree, 2L)
  expect_identical(unrooted$metadata$root_degree, 3L)
})

test_that("reference multifurcations remain unresolved", {
  validated <- validate_species_tree("(A,B,C,D);")
  expect_identical(validated$metadata$coordinate_count, 4L)
  expect_true(all(validated$coordinates$branch_type == "terminal"))
  counts <- setNames(validated$diagnostics$count, validated$diagnostics$code)
  expect_identical(counts[["MULTIFURCATING_REFERENCE_NODE"]], 1L)
})

test_that("multifurcating reference exposes only actual edge splits", {
  validated <- validate_species_tree("((A,B,C),(D,E));")
  expect_identical(
    validated$coordinates$canonical_split,
    c(
      "A||B..C..D..E",
      "A..C..D..E||B",
      "A..B..D..E||C",
      "A..B..C..E||D",
      "A..B..C..D||E",
      "A..B..C||D..E"
    )
  )
  phantom <- c(
    "A..B||C..D..E",
    "A..C||B..D..E",
    "B..C||A..D..E"
  )
  expect_false(any(phantom %in% validated$coordinates$canonical_split))
})

test_that("quoted labels and unsafe split labels use injective split keys", {
  validated <- validate_species_tree(
    "(('A one':1,'B..two':2):3,('C|three':4,D:5):6);"
  )
  expect_true(all(c("A one", "B..two", "C|three", "D") %in%
    validated$tip_labels))
  expect_true(all(startsWith(
    validated$coordinates$canonical_split,
    "HX1:"
  )))

  prefix_label <- validate_species_tree("('HX1:fake',B,C);")
  expect_true(all(startsWith(
    prefix_label$coordinates$canonical_split,
    "HX1:"
  )))
})

test_that("species-tree lengths are ignored even when unavailable markers occur", {
  validated <- validate_species_tree("(A:NaN,B:Inf,C:?);")
  expect_true(validated$valid)
  counts <- setNames(validated$diagnostics$count, validated$diagnostics$code)
  expect_identical(counts[["IGNORED_REFERENCE_BRANCH_LENGTH"]], 3L)
})

test_that("species-tree input accepts a file path and one phylo object", {
  path <- tempfile(fileext = ".nwk")
  writeLines("((A,B),(C,D));", path)
  from_file <- validate_species_tree(path)
  expect_true(from_file$valid)
  expect_identical(from_file$metadata$coordinate_count, 5L)

  phy <- ape::read.tree(text = "((A,B),(C,D));")
  from_phylo <- validate_species_tree(phy)
  expect_true(from_phylo$valid)
  expect_identical(from_phylo$source, "ape::phylo")
})

test_that("species-tree parser fails loudly on invalid structure", {
  expect_error(validate_species_tree("((A,B),A);"), "Duplicate terminal")
  expect_error(validate_species_tree("((A),B);"), "at least two children")
  expect_error(validate_species_tree("(A,B); trailing"), "extra content")
  expect_error(validate_species_tree("(A[&broken,B);"), "unterminated")
  expect_error(validate_species_tree(list()), "must be one")
  expect_error(validate_species_tree(structure(list(), class = "multiPhylo")),
               "exactly one tree")
})

test_that("Catnip10 input produces the expected 17-coordinate B axis", {
  validated <- validate_species_tree(catnip10_oracle$species_tree)
  expect_identical(validated$metadata$tip_count, 10L)
  expect_identical(validated$metadata$coordinate_count, 17L)
  expect_identical(validated$coordinates$coordinate_id, paste0("B", 1:17))
  type_counts <- table(validated$coordinates$branch_type)
  expect_identical(names(type_counts), c("internal", "terminal"))
  expect_identical(as.integer(type_counts), c(7L, 10L))

  frozen_axis <- utils::read.delim(
    test_path("fixtures/catnip10_species_axis.tsv"),
    header = TRUE,
    sep = "\t",
    quote = "",
    colClasses = "character",
    na.strings = character(0),
    stringsAsFactors = FALSE
  )
  expect_identical(
    validated$coordinates[c("coordinate_id", "canonical_split")],
    frozen_axis
  )
})
