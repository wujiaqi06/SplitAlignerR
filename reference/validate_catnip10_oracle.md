# Validate the bundled Catnip10 oracle data

Run deterministic checks for the bundled Catnip10 graph-oracle data. In
addition to data loading and accounting checks, the pure R node-edge
oracle is rerun for both deletion regimes and compared exactly with the
frozen matrix, per-cell ledger, and fusion groups. The Oracle remains
independent of the production C++ mapper; this helper validates the
Oracle track, not final release certification.

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
#> 5                    pure_R_graph_oracle_exact_global   PASS
#> 6                     pure_R_graph_oracle_exact_local   PASS
#>                                                                                                                         details
#> 1                                                                             catnip10_oracle contains global and local regimes
#> 2                                                                                                     NA_topo cells observed: 0
#> 3 global total=136 observed=72 NA_fuse=25 NA_struct=39 NA_topo=0; local total=136 observed=69 NA_fuse=24 NA_struct=43 NA_topo=0
#> 4                                                                         Expected each regime matrix to be 8 rows x 18 columns
#> 5                                                         136/136 primitive cells and all fusion groups match the frozen oracle
#> 6                                                         136/136 primitive cells and all fusion groups match the frozen oracle
```
