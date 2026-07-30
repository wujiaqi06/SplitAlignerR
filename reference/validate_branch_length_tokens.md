# Validate branch-length tokens

Parse branch-length tokens using the SplitAlignerR V1 numeric policy.
Parsing consumes the entire token, accepts explicit zero and every
representable finite decimal value, rejects non-finite values and values
that overflow or underflow to zero, and never converts software failure
markers to zero.

## Usage

``` r
validate_branch_length_tokens(tokens)
```

## Arguments

- tokens:

  A character vector of branch-length tokens. R missing values, empty
  strings, and recognized software failure markers are treated as
  unavailable numeric evidence.

## Value

A data frame with the original token, classification, acceptance flag,
parsed value, zero/negative flags, and diagnostic.

## Details

Finite negative values are retained for compatibility with phylogenetic
software output but receive a diagnostic because the nonnegative
numerical theorem does not cover them.

## Examples

``` r
validate_branch_length_tokens(c("0", "1e-8", "NaN", "1e9999"))
#>    token          classification accepted value is_zero is_negative
#> 1      0          finite_numeric     TRUE 0e+00    TRUE       FALSE
#> 2   1e-8          finite_numeric     TRUE 1e-08   FALSE       FALSE
#> 3    NaN software_failure_marker    FALSE    NA      NA          NA
#> 4 1e9999            out_of_range    FALSE    NA      NA          NA
#>                                               diagnostic
#> 1                                 accepted finite double
#> 2                                 accepted finite double
#> 3 recognized unavailable marker; never converted to zero
#> 4        numeric value is not finite in double precision
```
