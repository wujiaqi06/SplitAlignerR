# Versioned primitive branch exchange and scoped aliases

An additive development RDS interface retaining complete result, tree
and provenance. Single fixed branch-length profile only. Coordinates are
independent of B aliases and tree-local node numbers.

## Usage

``` r
export_splitaligner_exchange(result, species_tree, tree_source, producer,
  label_scheme, payload, file = NULL, branch_margin = 2L)
validate_splitaligner_exchange(x)
read_splitaligner_exchange(file)
transpose_splitaligner_exchange(x)
annotate_splitaligner_exchange(x, gene_id, tree = x$tree$phylo)
splitaligner_label_registry()
splitaligner_exchange_schema()
new_splitaligner_label_migration(x, to_scheme, target_aliases, authority,
  allow_synthetic = FALSE)
migrate_splitaligner_labels(x, migration, allow_synthetic = FALSE)
```

## Arguments

- result:

  A single fixed-mode splitaligner_result.

- species_tree, tree:

  Explicit complete phylo reference or display instance.

- tree_source:

  Explicit named provenance list with kind and id; original source bytes
  are preserved.

- producer:

  Declared source commit/tree/parent, dirty scope, file hashes and
  development provenance.

- label_scheme, to_scheme:

  Registered list with id and version.

- payload:

  Branch_length type, name, units, identity scale, origin and spec_id.

- file:

  New output path or existing input RDS, as appropriate.

- branch_margin:

  2 for gene by branch, explicitly 1 for branch by gene.

- x:

  A checked exchange envelope.

- gene_id:

  One exact gene key.

- target_aliases:

  Target B aliases in coordinate order.

- authority:

  Explicit synthetic or source-bound migration evidence.

- allow_synthetic:

  Explicit opt-in for synthetic fixture migration.

- migration:

  A migration bound to exact tree and ledgers.

## Value

An envelope, schema, registry, migration, or edge annotation table as
named by the function. Validation returns the input invisibly.

## Details

Schema 0.1.0-development. Unknown mode, payload, alias scope or
provenance and non-bijective root/edge representations are rejected. No
rerooting, pruning or composite expansion is performed. Tree geometry is
separate from gene values. See exchange_handoff/S1/API.md in the
development checkout for the full profile. La Terra reader and plotting
compatibility remain untested.
