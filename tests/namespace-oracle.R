# Exercise the installed package exactly as a downstream Imports user would.
stopifnot(!"package:SplitAlignerR" %in% search())
catnip10_oracle <- list(global = "unrelated object in the caller's workspace")
stopifnot(
  identical(SplitAlignerR::catnip10_matrix("global"),
            SplitAlignerR::catnip10_oracle$global$matrix),
  all(SplitAlignerR::validate_catnip10_oracle()$status == "PASS"),
  nrow(SplitAlignerR::catnip10_fusion_groups()) == 19L,
  !"package:SplitAlignerR" %in% search()
)
