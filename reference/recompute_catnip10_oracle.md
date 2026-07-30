# Recompute the Catnip10 graph oracle

Recompute a bundled Catnip10 deletion scenario with the independent pure
R node-edge oracle. The implementation tracks primitive edge membership
through explicit tip deletion and degree-2 contraction. It does not call
the C++ production core and does not use projected splits to classify
`NA_struct` or `NA_fuse`.

## Usage

``` r
recompute_catnip10_oracle(regime = c("global", "local"))
```

## Arguments

- regime:

  Deletion regime: `"global"` or `"local"`.

## Value

A list containing `matrix`, `status_long`, `fusion_groups`, and
`deletion_order`, with the same schemas as the corresponding bundled
frozen Catnip10 objects.

## Examples

``` r
rebuilt <- recompute_catnip10_oracle("global")
identical(rebuilt$matrix, catnip10_matrix("global"))
#> [1] TRUE
```
