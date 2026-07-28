# SplitAlignerR V1 release-candidate identity

This directory records package-internal release-engineering metadata for the
SplitAlignerR V1 candidate. It does not contain a reviewer verdict and does not
turn a release candidate into a final release.

- RELEASE_IDENTITY.json freezes package, core, schema, baseline, authority,
  and candidate identifiers.
- DEPENDENCY_CONTRACT.md records the package and replay dependency closure,
  including the litedown/commonmark vignette chain.
- KNOWN_LIMITATIONS.md records the V1 architecture and scope boundary.
- UNRESOLVED_ISSUES.md records operational observations that remain open.
- NUMERIC_SERIALIZATION_INVENTORY.tsv records the FIX006 numeric-to-text audit.
- The FIX006A session-option gate records requested and effective values
  separately; its optional `scipen=-999` row is not a portable PASS claim.
- The FIX006A Windows cold-start scripts provide bounded, fresh-process
  diagnostic evidence and do not modify or replace the numeric parser.
- The FIX007 Windows isolation gate preserves raw CRLF streams, derives all
  tables from one normalized parser view, passes frozen commit identity into
  archive snapshots, and builds a non-package bare-R diagnostic DLL with
  `R CMD SHLIB`. A separate fresh-process bare-C locale control records the
  effective runtime categories without pre-warming D1-D7. Core changes remain
  conditional on hosted A/B evidence.

The frozen `v0.1.0-rc1` and `v0.1.0-rc2` tags remain immutable historical
candidates. This source is the untagged Fix007 child of the accepted Fix006A
implementation; it is not RC3 and does not authorize a release. Only
after main-console acceptance may a separate release-identity child and
annotated `v0.1.0-rc3` tag be created. Tag-to-commit proof belongs in that later
external RECERT package.
