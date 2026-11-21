test_that("compact split ledgers preserve the frozen 9013 scientific records", {
  # Generated from the untouched 0.1.0.9013 installation, commit c50e175.
  # Covers whole-component recovery and source order, absent members, unknown
  # lengths, binary display-root sums, structured UTF-8 labels and 64-bit words.
  frozen <- readRDS(test_path("fixtures", "compact-split-9013.rds"))
  expect_identical(attr(frozen, "source_commit"),
                   "c50e175fbef958d78383442d0250c00dc060e315")
  for (case_name in names(frozen)) {
    case <- frozen[[case_name]]
    for (view in c("whole", "direct")) {
      expected <- case[[view]]
      actual <- align_branches(case$species, case$genes, fusion_view = view)
      for (field in names(expected)) {
        expect_identical(actual[[field]], expected[[field]],
                         info = paste(case_name, view, field))
      }
      # These columns remain public character vectors, including their NA
      # placement, after the internal backing becomes compact and deferred.
      expect_type(actual$state_ledger$projected_split, "character")
      expect_type(actual$composite_ledger$projected_split, "character")
    }
  }
})
