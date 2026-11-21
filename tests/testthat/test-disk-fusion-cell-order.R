test_that("disk fusion cells match in-memory pattern order across shards and repeated selections", {
  folder <- tempfile("panel-cell-order-")
  dir.create(folder)
  on.exit(unlink(folder, recursive = TRUE), add = TRUE)
  reference <- "(((((A,B),C),D),E),F,(G,H));"
  trees <- c(pair = "((((A:1,B:2):8,D:4):7,E:5):9,F:6,(G:7,H:8):1);",
             complete = "(((((A:1,B:2):3,C:3):5,D:4):7,E:5):9,F:6,(G:7,H:8):1);",
             triple = "(((A:1,B:2):15,E:5):9,F:6,(G:7,H:8):1);")
  fixed <- gsub(":1", ":2", trees, fixed = TRUE)
  names(fixed) <- names(trees)
  species_file <- file.path(folder, "reference")
  free_file <- file.path(folder, "free")
  fixed_file <- file.path(folder, "fixed")
  writeLines(reference, species_file)
  writeLines(paste0(names(trees), trees), free_file)
  writeLines(paste0(names(fixed), fixed), fixed_file)
  row_positions <- c(3L, 1L, 2L, 1L)
  for (view in c("whole", "direct")) {
    panel <- align_panel_to_disk(species_file, free_file, file.path(folder, view),
                                 mode = "paired", fixed_file = fixed_file,
                                 batch_size = 1L, fusion_view = view)
    catalog <- panel_fusion_patterns(panel)$coordinate_id
    expect_gte(length(catalog), 2L)
    pattern_positions <- c(2L, 1L, 2L)
    ids <- names(trees)[row_positions]
    patterns <- catalog[pattern_positions]
    for (role in c("free", "fixed")) {
      result <- align_branches(reference, if (role == "free") trees else fixed,
                                mode = role, fusion_view = view)
      expected <- fusion_cells(result, ids, patterns)
      observed <- read_panel_fusion_cells(panel, ids, patterns, role)
      expect_identical(observed, expected)
      expect_identical(observed$gene_id, rep(ids, times = length(patterns)))
      expect_identical(observed$composite_id, rep(patterns, each = length(ids)))
      expect_identical(read_panel_fusion_cells(panel, row_positions, pattern_positions, role),
                       expected)
      expect_identical(read_panel_fusion_cells(panel, character(), patterns, role),
                       fusion_cells(result, character(), patterns))
      expect_identical(read_panel_fusion_cells(panel, ids, integer(), role),
                       fusion_cells(result, ids, character()))
      expect_identical(read_panel_fusion_cells(panel, numeric(), character(), role),
                       fusion_cells(result, character(), character()))
      expect_error(read_panel_fusion_cells(panel, 0, patterns, role), "positive index")
      expect_error(read_panel_fusion_cells(panel, ids, 0, role), "positive index")
    }
  }
})
