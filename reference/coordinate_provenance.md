# Query coordinate member-set provenance

Return the deterministic primitive-member definition of one or more
result coordinates. Primitive rows contain themselves as their one
member; composite rows expose the complete frozen primitive member set.

## Usage

``` r
coordinate_provenance(result, coordinate_id = NULL)
```

## Arguments

- result:

  A `splitaligner_result` returned by
  [`align_branches()`](https://wujiaqi06.github.io/SplitAlignerR/reference/align_branches.md).

- coordinate_id:

  Optional character vector of exact coordinate IDs. The default returns
  all primitive and composite coordinates in result order.

## Value

A data frame with coordinate type, reference split where applicable,
member count/text, representation aliases, and a list-column containing
exact primitive members.

## Examples

``` r
species <- "((A:1,B:1):1,(C:1,D:1):1);"
result <- align_branches(species, "(A:1,B:2);")
coordinate_provenance(result, "F[B1|B2]")
#>   coordinate_id coordinate_type branch_type canonical_reference_split
#> 1      F[B1|B2]       composite   composite                      <NA>
#>   member_count member_text representation_alias_text primitive_members
#> 1            2       B1|B2                      <NA>            B1, B2
```
