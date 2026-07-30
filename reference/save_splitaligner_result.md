# Save a SplitAlignerR result

Save the complete layered result as one RDS file. The stored object
retains coordinate definitions, ledgers, diagnostics, conventions, and
core/schema identifiers required for checked reload.

## Usage

``` r
save_splitaligner_result(result, file, compress = TRUE, overwrite = FALSE)
```

## Arguments

- result:

  A `splitaligner_result` returned by
  [`align_branches()`](https://wujiaqi06.github.io/SplitAlignerR/reference/align_branches.md).

- file:

  Output RDS path.

- compress:

  Compression passed to
  [`saveRDS()`](https://rdrr.io/r/base/readRDS.html).

- overwrite:

  Logical; overwrite an existing file only when explicitly `TRUE`.

## Value

Invisibly, the normalized saved path.

## Examples

``` r
species <- "((A,B),(C,D));"
result <- align_branches(species, "((A:1,B:1),(C:1,D:1));")
path <- tempfile(fileext = ".rds")
save_splitaligner_result(result, path)
restored <- read_splitaligner_result(path)
identical(result, restored)
#> [1] TRUE
```
