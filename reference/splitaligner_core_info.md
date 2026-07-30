# SplitAligner C++ core metadata

Return versioned metadata for the compiled production-core boundary. The
graph oracle is intentionally reported separately because it is
implemented in pure R and must remain independent of the production C++
engine.

## Usage

``` r
splitaligner_core_info()
```

## Value

A named list containing core, schema, language, and numeric-policy
identifiers.

## Examples

``` r
splitaligner_core_info()
#> $core_version
#> [1] "0.1.0"
#> 
#> $schema_version
#> [1] "1.0.0"
#> 
#> $production_language
#> [1] "C++17"
#> 
#> $numeric_policy
#> [1] "finite-double-v1"
#> 
#> $oracle_language
#> [1] "pure R node-edge graph surgery"
#> 
#> $oracle_calls_production_core
#> [1] FALSE
#> 
```
