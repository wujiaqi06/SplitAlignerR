# Small end-to-end smoke of the installed SplitAlignerR development build.
# Usage: R_LIBS=<stage LIB> Rscript package_smoke.R
# Follows the README minimal example; every check is a real assertion.
suppressPackageStartupMessages(library(SplitAlignerR))

cat("package:", as.character(packageVersion("SplitAlignerR")), "\n")
cat("installed at:", find.package("SplitAlignerR"), "\n")

validation <- validate_catnip10_oracle()
print(validation[, c("check", "status")])
stopifnot(is.data.frame(validation), nrow(validation) > 0,
          all(validation$status == "PASS"))
for (regime in c("global")) {
  rebuilt <- recompute_catnip10_oracle(regime)
  stopifnot(identical(rebuilt$matrix, catnip10_matrix(regime)))
  cat("oracle recompute identical for regime", regime, "\n")
}

info <- splitaligner_core_info()
str(info)

tokens <- validate_branch_length_tokens(c("0", "1e-8", "NaN", "1e9999"))
print(tokens)

species <- "((A:1,B:1):1,(C:1,D:1):1);"
genes <- c(
  concordant = "((A:1,B:1):1,(C:1,D:1):1);",
  discordant = "((A:1,C:1):1,(B:1,D:1):1);",
  marker = "((A:NaN,B:1):1,(C:1,D:1):1);"
)
aligned <- align_branches(species, genes, mode = "free")
print(aligned$state_matrix)
print(aligned$numeric_matrix)
stopifnot(inherits(aligned, "splitaligner_result"),
          identical(dim(aligned$state_matrix), dim(aligned$numeric_matrix)),
          ncol(aligned$state_matrix) == length(genes) ||
            nrow(aligned$state_matrix) == length(genes))

# Lossless persistence round trip through a temp file.
path <- tempfile(fileext = ".rds")
save_splitaligner_result(aligned, path)
back <- read_splitaligner_result(path)
stopifnot(identical(back$state_matrix, aligned$state_matrix),
          identical(back$numeric_matrix, aligned$numeric_matrix))
unlink(path)
cat("SMOKE_ASSERTIONS_COMPLETED\n")
