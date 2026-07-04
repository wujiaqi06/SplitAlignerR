# Validate the bundled Catnip10 oracle data

Run deterministic sanity checks for the Catnip10 graph-oracle data
bundled in this public seed release. The checks are intentionally
narrow: they validate package data loading, status accounting, and the
absence of `NA_topo` in the discordance-free benchmark. They do not
claim that the empirical split-mapping engine is implemented.

## Usage

``` r
validate_catnip10_oracle()
```

## Value

A base `data.frame` with columns `check`, `status`, and `details`.
`status` is one of `PASS`, `FAIL`, or `DEFERRED`.

## Examples

``` r
validate_catnip10_oracle()
#>                                                 check status
#> 1                                  package_data_loads   PASS
#> 2 no_unexpected_NA_topo_in_discordance_free_benchmark   PASS
#> 3                             status_counts_available   PASS
#> 4                 matrix_dimensions_match_seed_oracle   PASS
#>                                                                                                                         details
#> 1                                                                             catnip10_oracle contains global and local regimes
#> 2                                                                                                     NA_topo cells observed: 0
#> 3 global total=136 observed=72 NA_fuse=25 NA_struct=39 NA_topo=0; local total=136 observed=69 NA_fuse=24 NA_struct=43 NA_topo=0
#> 4                                                                         Expected each regime matrix to be 8 rows x 18 columns
```
