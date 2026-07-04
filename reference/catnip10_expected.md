# Catnip10 benchmark expected oracle output

Return the deterministic expected gene-by-branch coordinate matrix of
the Catnip10 10-tip coordinate-audit benchmark for one taxon-deletion
regime. Values are kept as character strings so that numeric branch
lengths and the explicit missingness labels (`NA_struct`, `NA_fuse`) are
preserved exactly as emitted by the independent graph-theoretic oracle.
Rows are the full tree (`*_step0`) followed by seven cumulative deletion
steps; columns are the 17 primitive branch coordinates on the unrooted
axis (ten terminals `t1`–`t10` and seven internals `N_12`–`N_18`),
preceded by `gene_id`.

## Usage

``` r
catnip10_expected(regime = c("global", "local"))
```

## Arguments

- regime:

  Deletion regime: `"global"` (outgroup-first) or `"local"` (locally
  confined). Partial matching is allowed via
  [`match.arg()`](https://rdrr.io/r/base/match.arg.html).

## Value

A `data.frame` with 8 rows and 18 columns (`gene_id` plus the 17 branch
coordinates), all columns character.

## See also

[catnip10_oracle](https://wujiaqi06.github.io/SplitAlignerR/reference/catnip10_oracle.md)
for the full bundled benchmark object.

## Examples

``` r
g <- catnip10_expected("global")
dim(g)
#> [1]  8 18
g[["gene_id"]]
#> [1] "main_step0" "main_step1" "main_step2" "main_step3" "main_step4"
#> [6] "main_step5" "main_step6" "main_step7"
```
