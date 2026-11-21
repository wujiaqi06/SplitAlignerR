# Run with the actual package under test on .libPaths(), for example:
# R_LIBS=/tmp/test-library Rscript --vanilla tests/regression/direct-view-evidence.R /tmp/r-evidence.csv
library(SplitAlignerR)
output <- commandArgs(trailingOnly = TRUE)
if (length(output) != 1L || file.exists(output) || !dir.exists(dirname(output))) {
  stop("Supply one new evidence CSV path under an existing directory.")
}
script <- sub("^--file=", "", grep("^--file=", commandArgs(), value = TRUE))
fixture <- file.path(dirname(normalizePath(script, mustWork = TRUE)),
                     "..", "testthat", "fixtures", "direct-view-genes.nwk")
reference <- "((A,(B,C)),(D,E));"
records <- lapply(c("whole", "direct"), function(view) {
  result <- align_branches(reference, fixture, fusion_view = view)
  cells <- fusion_cells(result, coordinate_ids = "F[B2|B6]")
  out <- cells[, c("gene_id", "reference_state", "recovery_status", "numeric_status",
                   "construction_mode", "numeric_value")]
  out$view <- view
  out
})
write.csv(do.call(rbind, records), output, row.names = FALSE, na = "NA")
cat("Package:", as.character(packageVersion("SplitAlignerR")),
    "\nLibrary:", find.package("SplitAlignerR"), "\nEvidence:", normalizePath(output), "\n")
