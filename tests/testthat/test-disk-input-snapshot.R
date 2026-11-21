test_that("panel input hashes cover the bytes parsed during transient file edits", {
  tmp <- tempfile("input-snapshot-")
  dir.create(tmp)
  on.exit(unlink(tmp, recursive = TRUE), add = TRUE)
  ref <- file.path(tmp, "reference.nwk")
  trees <- file.path(tmp, "genes.nwk")
  original <- "((A,B),(C,D));"
  replacement <- "((A,C),(B,D));"
  writeLines(original, ref)
  writeLines("g((A:1,B:2):3,(C:4,D:5):6);", trees)
  hash <- digest::digest(file = ref, algo = "sha256")
  actual_read <- as_species_newick
  testthat::local_mocked_bindings(as_species_newick = function(input) {
    writeLines(replacement, ref)
    on.exit(writeLines(original, ref))
    actual_read(input)
  }, .package = "SplitAlignerR")
  panel <- align_panel_to_disk(ref, trees, file.path(tmp, "panel"))
  manifest <- readRDS(file.path(panel, "manifest.rds"))
  expect_identical(manifest$reference_newick, original)
  expect_identical(manifest$input_sha256[["reference"]], hash)
  expect_identical(readLines(ref), original)
  expect_true(all(read_panel_matrix(panel, "free_state", "g") == "mapped"))
})

test_that("read-only inputs use writable private snapshots that are removed", {
  tmp <- tempfile("readonly-input-snapshot-")
  dir.create(tmp)
  on.exit(unlink(tmp, recursive = TRUE, force = TRUE), add = TRUE)
  ref <- file.path(tmp, "reference.nwk")
  trees <- file.path(tmp, "genes.nwk")
  writeLines("((A,B),(C,D));", ref)
  writeLines("g((A:1,B:2):3,(C:4,D:5):6);", trees)
  Sys.chmod(c(ref, trees), mode = "0444", use_umask = FALSE)
  actual_read <- as_species_newick
  snapshot_dir <- NULL
  snapshot_writable <- FALSE
  testthat::local_mocked_bindings(as_species_newick = function(input) {
    snapshot_dir <<- dirname(input)
    snapshot_writable <<- all(bitwAnd(as.integer(file.info(
      list.files(snapshot_dir, full.names = TRUE))$mode), 128L) != 0L)
    actual_read(input)
  }, .package = "SplitAlignerR")
  panel <- align_panel_to_disk(ref, trees, file.path(tmp, "panel"))
  expect_true(snapshot_writable)
  expect_false(dir.exists(snapshot_dir))
  expect_true(all(bitwAnd(as.integer(file.info(c(ref, trees))$mode), 128L) == 0L))
  expect_true(all(read_panel_matrix(panel, "free_state", "g") == "mapped"))
})
