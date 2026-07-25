# SplitAlignerR V1 release-candidate identity

This directory records package-internal release-engineering metadata for the
SplitAlignerR V1 candidate. It does not contain a reviewer verdict and does not
turn a release candidate into a final release.

- RELEASE_IDENTITY.json freezes package, core, schema, baseline, authority,
  and candidate identifiers.
- DEPENDENCY_CONTRACT.md records the package and replay dependency closure,
  including the litedown/commonmark vignette chain.
- KNOWN_LIMITATIONS.md records the V1 architecture and scope boundary.

The authoritative RC source commit is the commit to which the annotated
v0.1.0-rc1 tag peels. The commit cannot embed its own hash without creating
a self-reference; tag-to-commit proof belongs in the external RECERT package.
