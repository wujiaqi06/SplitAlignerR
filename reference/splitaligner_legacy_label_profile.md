# A named source-bound historical branch alias profile

Rebuild coordinates from explicitly named original tree bytes and bind
the two user-provided historical tables. No historical numerical
analysis is performed.

## Usage

``` r
audit_splitaligner_legacy_labels(old_ape_file, old_new_file, tree_file, file = NULL)
validate_splitaligner_legacy_profile(profile)
legacy_profile_label_migration(x, profile, to_scheme)
```

## Arguments

- old_ape_file, old_new_file:

  Exact original user tables.

- tree_file:

  One of the three explicitly named original tree sources.

- file:

  Optional new RDS destination.

- profile:

  A source-bound profile.

- x:

  A checked exchange with the exact reference instance and ordered
  ledger.

- to_scheme:

  An explicit registered scheme list with id and version.

## Value

A checked profile or a bound migration. Validation returns the profile
invisibly.

## Details

Scope is marine302-user-bound-20260908-v1 only. Unknown provenance,
tree/ledger mismatch, unrecognized nonbranch records and arbitrary
claimed authority are rejected. The exact final semicolon record is
preserved separately. This is coordinate agreement for named sources,
not all-version or whole-generation-history certification.
