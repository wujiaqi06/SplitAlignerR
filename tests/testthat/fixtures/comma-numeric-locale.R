.libPaths(commandArgs(trailingOnly = TRUE))

# Check the effective decimal point with formatting; R-level locale queries
# have crashed specific Windows R builds in cold sessions.
found <- FALSE
for (candidate in c("de_DE.UTF-8", "fr_FR.UTF-8", "German_Germany.1252")) {
  active <- suppressWarnings(Sys.setlocale("LC_NUMERIC", candidate))
  if (nzchar(active) && identical(sprintf("%.1f", 0.5), "0,5")) {
    found <- TRUE
    break
  }
}
if (!found) quit(save = "no", status = 77L)
result <- SplitAlignerR::validate_branch_length_tokens(
  c("0.5", "1.", ".5", "4.9406564584124654e-324", "1e-999", "1e999", "0,5")
)
stopifnot(identical(result$value[1:3], c(0.5, 1, 0.5)),
          result$value[4] > 0, result$value[4] < .Machine$double.xmin,
          identical(result$classification[5:7],
                    c("out_of_range", "out_of_range", "invalid_numeric")),
          identical(sprintf("%.1f", 0.5), "0,5"))

ref <- "((A,B),C,(D,(E,F)));"
gene <- "((A,B):0.26,D,(E,F):0.17);"
r <- SplitAlignerR::align_branches(ref, c(g1 = gene))
tokens <- SplitAlignerR::free_fusion_groups(r)$final_token
phy <- ape::read.tree(text = "((A,B):1,D,(E,F):1);")
phy$edge.length[which(phy$edge[,2] > length(phy$tip.label))] <- c(0.26, 0.17)
phy_result <- SplitAlignerR::align_branches(ref, phy, gene_ids = "g1")
stopifnot(identical(tokens, "0.26000000000000001"),
          identical(phy_result$numeric_matrix, r$numeric_matrix))
