# Write the branch support table and annotated reference tree

Export the two Support outputs already computed by
[`align_branches()`](https://wujiaqi06.github.io/SplitAlignerR/reference/align_branches.md).
Each row describes one original reference branch. An internal branch is
eligible for a gene when its projected split belongs to it alone and
retains at least two taxa on each side. Support is the number recovered
divided by the number eligible, irrespective of branch lengths. Numeric
internal labels in the Newick tree give percentages. A percentage of
zero is printed as 0. A branch with no eligible genes has an NA
percentage and an empty tree label. If the display root divides one
internal branch, both halves show its label. The table uses R's
primitive `coordinate_id` labels. `n_dec` counts eligible genes and
`n_rec` counts recoveries. Match `coordinate_id` against the result's
`primitive_coordinates` to look up the taxon split.

## Usage

``` r
write_branch_support(result, output_dir)
```

## Arguments

- result:

  A single fixed- or free-mode result returned by
  [`align_branches()`](https://wujiaqi06.github.io/SplitAlignerR/reference/align_branches.md).

- output_dir:

  A new directory in an existing parent directory.

## Value

Invisibly, the named paths to `support.tsv` (table) and `support.nwk`
(tree).

## Examples

``` r
genes <- c(same = "((A,B),(C,D));", different = "((A,C),(B,D));")
result <- align_branches("((A,B),(C,D));", genes)
result$support_newick
#> [1] "((A,B)50,(C,D)50);"
destination <- tempfile()
paths <- write_branch_support(result, destination)
readLines(paths[["tree"]])
#> [1] "((A,B)50,(C,D)50);"
unlink(destination, recursive = TRUE)
```
