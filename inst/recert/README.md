# SplitAlignerR V1 release-candidate identity

This directory records package-internal release-engineering metadata for the
SplitAlignerR V1 candidate. It does not contain a reviewer verdict and does not
turn a release candidate into a final release.

- RELEASE_IDENTITY.json freezes package, core, schema, baseline, authority,
  and candidate identifiers.
- DEPENDENCY_CONTRACT.md records the package and replay dependency closure,
  including the litedown/commonmark vignette chain.
- KNOWN_LIMITATIONS.md records the V1 architecture and scope boundary.

The Fix005 source is a pre-tag candidate for `v0.1.0-rc2`. The frozen
`v0.1.0-rc1` tag remains immutable and is not submitted to Pro. An annotated
RC2 tag may be created only after main-console acceptance; tag-to-commit proof
belongs in the later external RECERT package.
