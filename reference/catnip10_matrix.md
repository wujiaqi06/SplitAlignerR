# Catnip10 wide primitive-coordinate matrix

Return the bundled wide graph-oracle matrix for one Catnip10 deletion
regime.

## Usage

``` r
catnip10_matrix(regime = c("global", "local"))
```

## Arguments

- regime:

  Deletion regime: `"global"` or `"local"`.

## Value

A base `data.frame` with `gene_id` plus 17 primitive branch coordinates.

## Examples

``` r
catnip10_matrix("global")
#>      gene_id         t10         N_12           t1         N_13           t8
#> 1 main_step0 1.464364133 0.1387101677 0.9888917289 0.9466682326 0.0824375581
#> 2 main_step1   NA_struct      NA_fuse 0.9888917289 0.9466682326 0.0824375581
#> 3 main_step2   NA_struct      NA_fuse    NA_struct      NA_fuse 0.0824375581
#> 4 main_step3   NA_struct      NA_fuse    NA_struct      NA_fuse    NA_struct
#> 5 main_step4   NA_struct      NA_fuse    NA_struct      NA_fuse    NA_struct
#> 6 main_step5   NA_struct      NA_fuse    NA_struct      NA_fuse    NA_struct
#> 7 main_step6   NA_struct    NA_struct    NA_struct    NA_struct    NA_struct
#> 8 main_step7   NA_struct    NA_struct    NA_struct    NA_struct    NA_struct
#>           N_14         N_15           t7           t4         t9         N_16
#> 1 0.5142117843 0.3902034671 0.9057381309 0.4469696281 0.83600426 0.7375956178
#> 2 0.5142117843 0.3902034671 0.9057381309 0.4469696281 0.83600426      NA_fuse
#> 3 0.5142117843 0.3902034671 0.9057381309 0.4469696281 0.83600426      NA_fuse
#> 4      NA_fuse 0.3902034671 0.9057381309 0.4469696281 0.83600426      NA_fuse
#> 5      NA_fuse      NA_fuse    NA_struct      NA_fuse 0.83600426      NA_fuse
#> 6      NA_fuse    NA_struct    NA_struct    NA_struct    NA_fuse      NA_fuse
#> 7    NA_struct    NA_struct    NA_struct    NA_struct  NA_struct    NA_struct
#> 8    NA_struct    NA_struct    NA_struct    NA_struct  NA_struct    NA_struct
#>           N_17           t5           t2           N_18           t3
#> 1 0.8110551413 0.3881082828 0.6851697294 0.003948338795 0.8329160803
#> 2 0.8110551413 0.3881082828 0.6851697294 0.003948338795 0.8329160803
#> 3 0.8110551413 0.3881082828 0.6851697294 0.003948338795 0.8329160803
#> 4 0.8110551413 0.3881082828 0.6851697294 0.003948338795 0.8329160803
#> 5 0.8110551413 0.3881082828 0.6851697294 0.003948338795 0.8329160803
#> 6 0.8110551413 0.3881082828 0.6851697294 0.003948338795 0.8329160803
#> 7      NA_fuse 0.3881082828 0.6851697294        NA_fuse 0.8329160803
#> 8      NA_fuse    NA_struct      NA_fuse        NA_fuse 0.8329160803
#>               t6
#> 1 0.007334146881
#> 2 0.007334146881
#> 3 0.007334146881
#> 4 0.007334146881
#> 5 0.007334146881
#> 6 0.007334146881
#> 7 0.007334146881
#> 8 0.007334146881
```
