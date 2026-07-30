# SplitAlignerR release and development identity

This directory records package-internal release-engineering metadata. The
immutable `v0.1.0` source passed independent Pro RECERT. Package version
`0.1.0.9000` is post-release development and is not covered by that decision.

- RELEASE_IDENTITY.json distinguishes the certified release identity from the
  current development version while retaining historical candidate identifiers.
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

The frozen `v0.1.0-rc1`, `v0.1.0-rc2`, and `v0.1.0-rc3` tags remain immutable
historical candidates. The annotated final tag `v0.1.0` peels to commit
`17a0927095c7a067817bf598a2556cbe7348a6d0`; tag existence and peeled-commit
identity are established by external release verification. Later development
commits must not be described as part of the certified frozen source.
