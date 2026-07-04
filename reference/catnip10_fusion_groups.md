# Catnip10 fused-coordinate groups

Return the bundled graph-oracle fused-coordinate membership table for
one or both Catnip10 deletion regimes.

## Usage

``` r
catnip10_fusion_groups(regime = c("all", "global", "local"))
```

## Arguments

- regime:

  Character; `"all"` returns both bundled regimes, otherwise one of
  `"global"` or `"local"`.

## Value

A base `data.frame`. When `regime = "all"`, a leading `regime` column is
added.

## Examples

``` r
head(catnip10_fusion_groups())
#>   regime    gene_id step_id merge_group_id expected_fused_length group_size
#> 1 global main_step1       1           MG01          0.8763057855          2
#> 2 global main_step2       2           MG01           1.822974018          3
#> 3 global main_step3       3           MG01           2.337185802          4
#> 4 global main_step4       4           MG01           2.337185802          4
#> 5 global main_step4       4           MG02          0.8371730952          2
#> 6 global main_step5       5           MG01           3.173190062          5
#>   benchmark_unrooted_members
#> 1                  N_12|N_16
#> 2             N_12|N_13|N_16
#> 3        N_12|N_13|N_14|N_16
#> 4        N_12|N_13|N_14|N_16
#> 5                    N_15|t4
#> 6     N_12|N_13|N_14|N_16|t9
```
