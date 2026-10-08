# SplitAlignerR 0.1.0.9002 — La Terra development backend

This prerelease supplies the exact source archive required by La Terra's current exchange importer.

- Package version: 0.1.0.9002
- Exchange schema: 0.2.0-development
- Content-hash format: SAR-C14N-1-SHA256
- License: GPL-3
- Source archive SHA256: c4fcc16cce3aaf90189a686b57dd0eadba2d20fccfd246d42deeef353f83522f

Download the attached `SplitAlignerR_0.1.0.9002.tar.gz` and `SHA256SUMS` for installation. The tag contains the corresponding pre-build source snapshot; the attached archive preserves the original R CMD build output, including DESCRIPTION build metadata and build/partial.rdb.

Use R 4.2 or later for La Terra, with Rcpp and a C++17 compiler toolchain available for this backend. Install in a separate library. The existing integration evidence is scoped to R 4.4.2 on macOS arm64, in C and UTF-8 locales. Other platforms and R versions are not newly qualified by this publication.

This is a development compatibility distribution, not a new stable SplitAlignerR release or an NRP3/native qualification. The stable v0.1.0 release and the default branch remain unchanged. No analyses or tests were rerun for this publication; existing source bytes and scoped integration evidence are preserved.
