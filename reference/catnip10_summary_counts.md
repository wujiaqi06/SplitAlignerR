# Catnip10 benchmark status counts

Summarize the bundled Catnip10 graph-oracle benchmark by deletion regime
and primitive-cell status. The benchmark is discordance-free, so
`NA_topo` is expected to be zero in this benchmark fixture.

## Usage

``` r
catnip10_summary_counts(regime = c("all", "global", "local"))
```

## Arguments

- regime:

  Character; `"all"` returns both bundled regimes, otherwise one of
  `"global"` or `"local"`.

## Value

A base `data.frame` with columns `regime`, `observed`, `NA_fuse`,
`NA_struct`, `NA_topo`, and `total`.

## Examples

``` r
catnip10_summary_counts()
#>   regime observed NA_fuse NA_struct NA_topo total
#> 1 global       72      25        39       0   136
#> 2  local       69      24        43       0   136
```
