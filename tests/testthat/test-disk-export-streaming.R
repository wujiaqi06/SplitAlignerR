test_that("fusion exports prepare each shard once and construct only one compact gene row", {
  folder <- tempfile("panel-streaming-")
  dir.create(folder)
  on.exit(unlink(folder, recursive = TRUE), add = TRUE)
  reference <- "(((((A,B),C),D),E),F,(G,H));"
  trees <- c(
    pair = "((((A:1,B:2):8,D:4):7,E:5):9,F:6,(G:7,H:8):1);",
    complete = "(((((A:1,B:2):3,C:3):5,D:4):7,E:5):9,F:6,(G:7,H:8):1);",
    triple = "(((A:1,B:2):15,E:5):9,F:6,(G:7,H:8):1);",
    zero = "((((A:0,B:0):0,D:0):0,E:0):0,F:0,(G:0,H:0):0);",
    absent = "(A:1,B:2,D:4,E:5,F:6,G:7,H:8);",
    missing = "((((A:1,B:2),D:4):7,E:5):9,F:6,(G:7,H:8):1);"
  )
  fixed <- gsub(":1", ":2", trees, fixed = TRUE)
  names(fixed) <- names(trees)
  species_file <- file.path(folder, "reference")
  free_file <- file.path(folder, "free")
  fixed_file <- file.path(folder, "fixed")
  writeLines(reference, species_file)
  writeLines(paste0(names(trees), trees), free_file)
  writeLines(paste0(names(fixed), fixed), fixed_file)

  actual_prepare <- .fusion_prepare
  actual_native <- cpp_fusion_cells
  scanned <- integer()
  native <- list()
  testthat::local_mocked_bindings(
    .fusion_prepare = function(result, definitions) {
      scanned <<- c(scanned, nrow(result$state_ledger))
      actual_prepare(result, definitions)
    },
    cpp_fusion_cells = function(owners, sizes, recovered, lengths, primitive_count,
                                gene_rows, target_members, whole, details) {
      native[[length(native) + 1L]] <<- c(owners = length(owners),
                                        components = length(sizes), rows = length(gene_rows))
      actual_native(owners, sizes, recovered, lengths, primitive_count,
                    gene_rows, target_members, whole, details)
    },
    .package = "SplitAlignerR"
  )
  for (view in c("whole", "direct")) {
    panel <- align_panel_to_disk(species_file, free_file, file.path(folder, view),
                                 mode = "paired", fixed_file = fixed_file,
                                 batch_size = 3L, fusion_view = view)
    m <- panel_manifest(panel)
    axes <- c(m$branches, m$patterns$coordinate_id)
    expect_gt(nrow(m$patterns), 0L)
    for (role in c("free", "fixed")) {
      result <- align_branches(reference, if (role == "free") trees else fixed,
                                mode = role, fusion_view = view)
      values <- result$numeric_matrix[, axes, drop = FALSE]
      expected <- c(paste(c("gene_id", axes), collapse = "\t"),
                    vapply(seq_len(nrow(values)), function(i) {
                      paste(c(rownames(values)[i], legacy_numeric_text(values[i, ])), collapse = "\t")
                    }, character(1)))
      scanned <- integer()
      native <- list()
      file <- file.path(folder, paste0(view, "-", role, ".tsv"))
      export_panel_matrix(panel, file, paste0(role, "_length"), include_fusions = TRUE)
      expect_identical(readBin(file, "raw", n = file.info(file)$size),
                       charToRaw(paste0(paste(expected, collapse = "\n"), "\n")))
      # These assertions guard the resource bound, not a wall-clock threshold:
      # every primitive ledger row is prepared once and native calls receive
      # only one gene's owners/components, never the full shard's arrays.
      expect_length(scanned, nrow(m$shards))
      expect_equal(sum(scanned), length(m$genes) * length(m$branches))
      expect_length(native, length(m$genes))
      work <- do.call(rbind, native)
      expect_true(all(work[, "rows"] == 1L))
      expect_true(all(work[, "owners"] == length(m$branches)))
      expect_true(all(work[, "components"] <= length(m$branches)))
    }
  }
})
