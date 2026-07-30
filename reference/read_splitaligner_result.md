# Read a SplitAlignerR result

Reload a result saved by
[`save_splitaligner_result()`](https://wujiaqi06.github.io/SplitAlignerR/reference/save_splitaligner_result.md)
and reject incomplete, corrupted-at-the-object-level, or incompatible
core/schema objects.

## Usage

``` r
read_splitaligner_result(file, check_version = TRUE)
```

## Arguments

- file:

  Existing RDS path.

- check_version:

  Logical; require the stored core and schema versions to match the
  currently loaded package.

## Value

A validated `splitaligner_result`.

## Examples

``` r
species <- "((A,B),(C,D));"
result <- align_branches(species, "((A:1,B:1),(C:1,D:1));")
path <- tempfile(fileext = ".rds")
save_splitaligner_result(result, path)
read_splitaligner_result(path)
#> <splitaligner_result> 1 genes x 5 primitive coordinates; 0 composite coordinates
#>   mapped=5  NA_struct=0  NA_fuse=0  NA_topo=0
#>   core=0.1.0  schema=1.0.0  mode=free
```
